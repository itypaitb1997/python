"""Remote Command Worker fetching and executing remote instructions."""
import threading
import subprocess
import json
from typing import Callable, Dict, Any, Optional
from app.api_client import ApiClient
from app.database import Database, get_utc_now
from app.logger import setup_logger
from app.constants import CommandStatus

logger = setup_logger("command_worker")


class CommandWorker(threading.Thread):
    def __init__(
        self,
        api_client: ApiClient,
        db: Database,
        handlers: Optional[Dict[str, Callable[[Dict[str, Any]], bool]]] = None,
        poll_interval: int = 15,
        identity: Optional[Any] = None,
    ):
        super().__init__(daemon=True, name="CommandWorker")
        self.api_client = api_client
        self.db = db
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self.handlers = handlers or {}
        self.identity = identity

    def register_handler(self, command_name: str, handler: Callable[[Dict[str, Any]], bool]) -> None:
        self.handlers[command_name] = handler

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info(f"Command worker started (poll: {self.poll_interval}s)")
        while not self._stop_event.is_set():
            try:
                self.poll_commands()
            except Exception as e:
                logger.warning(f"Error checking remote commands: {e}")

            if self._stop_event.wait(timeout=self.poll_interval):
                break
        logger.info("Command worker stopped")

    def poll_commands(self) -> None:
        url = "agent/commands"
        uuid_val = getattr(self.identity, "device_uuid", None) or getattr(self.api_client, "_device_uuid", None)
        if uuid_val:
            url = f"agent/commands?device_uuid={uuid_val}"
        resp = self.api_client.get(url, max_retries=1)
        if resp.status_code != 200:
            return

        commands = resp.json()
        if not isinstance(commands, list):
            commands = [commands] if commands else []

        for cmd in commands:
            cmd_id = cmd.get("id")
            command_name = cmd.get("command")
            payload = cmd.get("payload_json") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}

            if cmd_id and command_name:
                self.execute_command(cmd_id, command_name, payload)

    def execute_command(self, cmd_id: str, command_name: str, payload: Dict[str, Any]) -> None:
        logger.info(f"Executing remote command: {command_name} (ID: {cmd_id})")
        # Record into local SQLite
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO commands (id, command, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status = 'RUNNING', updated_at = ?
                """,
                (cmd_id, command_name, json.dumps(payload), CommandStatus.RUNNING.value, get_utc_now(), get_utc_now(), get_utc_now()),
            )

        success = False
        error_message = None

        try:
            if command_name in self.handlers:
                success = self.handlers[command_name](payload)
            elif command_name == "REBOOT_DEVICE":
                self._send_ack(cmd_id, CommandStatus.SUCCESS.value)
                def _do_reboot():
                    import time
                    time.sleep(1.5)
                    for cmd in [["sudo", "systemctl", "reboot"], ["systemctl", "reboot"], ["sudo", "reboot"], ["reboot"]]:
                        try:
                            subprocess.run(cmd, check=True)
                            break
                        except Exception:
                            continue
                threading.Thread(target=_do_reboot, daemon=True).start()
                return
            elif command_name == "SHUTDOWN_DEVICE":
                self._send_ack(cmd_id, CommandStatus.SUCCESS.value)
                subprocess.Popen(["poweroff"])
                return
            else:
                error_message = f"Unsupported command handler: {command_name}"
                logger.warning(error_message)
        except Exception as e:
            error_message = str(e)
            logger.error(f"Execution error for command {command_name}: {e}")

        status = CommandStatus.SUCCESS.value if success and not error_message else CommandStatus.FAILED.value
        self._send_ack(cmd_id, status, error_message)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE commands SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (status, error_message, get_utc_now(), cmd_id),
            )

    def _send_ack(self, cmd_id: str, status: str, error_message: Optional[str] = None) -> None:
        try:
            ack_payload = {"status": status}
            if error_message:
                ack_payload["error_message"] = error_message
            self.api_client.post(f"agent/commands/{cmd_id}/ack", json=ack_payload, max_retries=2)
        except Exception as e:
            logger.warning(f"Could not send ack for command {cmd_id}: {e}")
