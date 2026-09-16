"""Main entry point for FarLink Agent."""
import sys
import time
import signal
from typing import Dict, Any, Optional
from app.config import config
from app.logger import setup_logger
from app.database import Database
from app.device_identity import DeviceIdentity
from app.api_client import ApiClient
from app.auth import AuthManager
from app.health_monitor import HealthMonitor
from app.heartbeat import HeartbeatWorker
from app.config_manager import ConfigManager
from app.command_worker import CommandWorker
from app.sync_manager import SyncManager
from app.test_runner import TestRunner
from app.lcd_display import LCDDisplay
from app.button_handler import ButtonHandler
from app.network_diagnostics import NetworkDiagnostics
from app.cli_display import CLIDisplay

logger = setup_logger("agent_main", log_file=config.log_path)


class FarlinkAgent:
    def __init__(self):
        logger.info("Initializing FarLink Agent...")
        self.db = Database(config.db_path)
        self.identity = DeviceIdentity(self.db)
        self.api_client = ApiClient(config.api_url, timeout=config.http_timeout)
        self.api_client.set_device_uuid(self.identity.device_uuid)
        self.auth = AuthManager(self.api_client, self.identity)
        self.health = HealthMonitor()
        self.test_runner = TestRunner()
        self.sync_manager = SyncManager(self.db, self.api_client, identity=self.identity)
        self.config_manager = ConfigManager(self.db, self.api_client)
        self.lcd = LCDDisplay()

        # Remote command worker
        self.command_worker = CommandWorker(self.api_client, self.db, identity=self.identity)
        self._register_commands()

        # Heartbeat worker
        self.heartbeat_worker = HeartbeatWorker(
            api_client=self.api_client,
            identity=self.identity,
            health_monitor=self.health,
            interval=config.heartbeat_interval,
        )

        # Hardware buttons
        self.button_handler = ButtonHandler(
            pin_start=config.pin_start,
            pin_reset=config.pin_reset,
            on_start_press=self.on_start_button,
            on_reset_press=self.on_reset_button,
        )

        self.server_connected: bool = False
        self.latest_notification: str = "Initializing FarLink Go Agent..."
        self.running = True

    def _apply_config_updates(self) -> None:
        """Apply active config updates to running workers."""
        cfg = self.config_manager.active_config
        hb_interval = int(cfg.get("heartbeat_interval", config.heartbeat_interval))
        self.heartbeat_worker.set_interval(hb_interval)
        self.heartbeat_worker.config_version = self.config_manager.get_active_version()

    def _sync_config_command(self, payload: Dict[str, Any]) -> bool:
        logger.info("SYNC_CONFIG command received from web")
        if self.config_manager.fetch_and_sync():
            self._apply_config_updates()
        return True

    def _sync_data_command(self, payload: Dict[str, Any]) -> bool:
        logger.info("SYNC_DATA command received from web: syncing local SQLite test results")
        synced = self.sync_manager.sync_pending()
        logger.info(f"SYNC_DATA completed: {synced} test results synced to web")
        return True

    def _upload_log_command(self, payload: Dict[str, Any]) -> bool:
        logger.info("UPLOAD_LOG command received from web")
        try:
            import os
            log_lines = []
            for path in ("agent.log", "farlink_agent.log", "app.log"):
                if os.path.exists(path):
                    with open(path, "r") as f:
                        log_lines = f.readlines()[-50:]
                    break
            self.api_client.post("agent/logs", json={
                "device_uuid": self.identity.device_uuid,
                "level": "INFO",
                "logs": "".join(log_lines),
            })
            return True
        except Exception as e:
            logger.warning(f"Failed to upload log: {e}")
            return False

    def _restart_agent_command(self, payload: Dict[str, Any]) -> bool:
        logger.info("RESTART_AGENT command received: scheduling restart")
        def _delayed_stop():
            import time
            import os
            time.sleep(2.0)
            logger.info("Restarting agent process...")
            self.shutdown()
            try:
                import subprocess
                subprocess.run(["sudo", "systemctl", "restart", "farlink-agent"], timeout=5)
            except Exception:
                pass
            os._exit(0)
        import threading
        threading.Thread(target=_delayed_stop, daemon=True).start()
        return True

    def _register_commands(self) -> None:
        self.command_worker.register_handler("SYNC_CONFIG", self._sync_config_command)
        self.command_worker.register_handler("RUN_TEST", lambda p: self.run_test_command(p))
        self.command_worker.register_handler("SYNC_DATA", self._sync_data_command)
        self.command_worker.register_handler("UPLOAD_LOG", self._upload_log_command)
        self.command_worker.register_handler("RESTART_AGENT", self._restart_agent_command)

    def _render_dashboard(self, last_test: Optional[Dict[str, Any]] = None, test_running: bool = False) -> None:
        """Render live Matrix 3.5 inch terminal dashboard in English."""
        try:
            pending_count = self.sync_manager.get_pending_count()
            CLIDisplay.render(
                identity=self.identity,
                health=self.health,
                db=self.db,
                active_config=self.config_manager.active_config,
                api_url=config.api_url,
                last_test=last_test,
                test_running=test_running,
                server_connected=self.server_connected,
                notification=self.latest_notification,
                pending_sync_count=pending_count,
            )
        except Exception as e:
            logger.debug(f"CLI display render error: {e}")

    def on_start_button(self) -> None:
        logger.info("Start test triggered by physical button")
        self.latest_notification = "Running diagnostic speed test... Please wait."
        self.lcd.display_status("Starting Test...", "Please wait")
        self._render_dashboard(test_running=True)

        result = self.test_runner.run_speed_test()
        self.sync_manager.enqueue_result(result)
        
        # Try syncing if online
        synced = self.sync_manager.sync_pending()
        self.server_connected = self.api_client.is_connected
        pending_cnt = self.sync_manager.get_pending_count()

        if self.server_connected:
            self.latest_notification = f"Test finished (DL: {result['download_mbps']} Mbps). Synced with cloud."
        else:
            self.latest_notification = f"Test finished (DL: {result['download_mbps']} Mbps). Saved locally ({pending_cnt} queued)."

        self.heartbeat_worker.last_test_at = result["finished_at"]
        self.lcd.show_test_result(
            dl_mbps=result["download_mbps"],
            ul_mbps=result["upload_mbps"],
            latency=result.get("latency_ms"),
        )
        self._render_dashboard(last_test=result, test_running=False)

    def on_reset_button(self) -> None:
        logger.info("Reset triggered by physical button")
        self.latest_notification = "Re-evaluating network diagnostics & connection..."
        self.lcd.display_status("Device Resetting", "Re-init network")
        
        # Trigger network diagnostic and probe server
        diag = NetworkDiagnostics.run_full_diagnostics()
        self.server_connected = self.api_client.check_connection(timeout=2)

        if self.server_connected:
            srv_msg = "Server: Connected"
            self.latest_notification = "Network re-checked: Internet & FarLink Cloud ONLINE."
        else:
            srv_msg = "Server: Disconnected"
            self.latest_notification = "Network re-checked: Standalone offline mode active."

        net_msg = "Net: OK" if diag.get("internet_connected") else "Net: Offline"
        self.lcd.display_status(f"Claim: {self.identity.claim_code}", f"{net_msg} | {srv_msg}")
        self._render_dashboard()

    def run_test_command(self, payload: Dict[str, Any]) -> bool:
        server_ip = payload.get("server_ip")
        res = self.test_runner.run_speed_test(server_ip=server_ip)
        self.sync_manager.enqueue_result(res)
        self.sync_manager.sync_pending()
        self.server_connected = self.api_client.is_connected
        self.heartbeat_worker.last_test_at = res["finished_at"]
        self.latest_notification = f"Remote test completed (DL: {res['download_mbps']} Mbps)."
        self._render_dashboard(last_test=res)
        return True

    def start(self) -> None:
        logger.info(f"Agent Device UUID: {self.identity.device_uuid}")
        logger.info(f"Agent Claim Code: {self.identity.claim_code}")

        # Check server connection on startup
        self.server_connected = self.api_client.check_connection(timeout=2)
        if self.server_connected:
            self.latest_notification = "Connected to FarLink Cloud. Synchronizing..."
            self.auth.register_device()
        else:
            self.latest_notification = "Server disconnected. Operating in offline standalone mode."
            logger.info("[OFFLINE] Operating in standalone offline mode. All metrics stored locally.")

        self.lcd.display_status(
            f"ID:{self.identity.claim_code[:12]}",
            "ONLINE" if self.server_connected else "OFFLINE"
        )

        # Start workers
        self.heartbeat_worker.start()
        self.command_worker.start()

        # Check for remote config on boot if connected
        if self.server_connected and self.config_manager.fetch_and_sync():
            self._apply_config_updates()

        # Initial dashboard render
        self._render_dashboard()

        sync_counter = 0
        connection_check_counter = 0

        while self.running:
            try:
                time.sleep(3)
                sync_counter += 3
                connection_check_counter += 3

                # Periodically probe server status
                if connection_check_counter >= 15:
                    prev_state = self.server_connected
                    self.server_connected = self.api_client.check_connection(timeout=2)
                    connection_check_counter = 0

                    # Detect transition from offline -> online
                    if not prev_state and self.server_connected:
                        logger.info("[RECONNECTED] Server connection restored. Synchronizing queued data...")
                        self.auth.register_device()
                        synced = self.sync_manager.sync_pending()
                        if self.config_manager.fetch_and_sync():
                            self._apply_config_updates()
                        self.latest_notification = f"Server reconnected! {synced} test results automatically synced."

                active_cfg = self.config_manager.active_config
                sync_interval = int(active_cfg.get("sync_interval", 60))

                if sync_counter >= sync_interval:
                    if self.server_connected:
                        self.sync_manager.sync_pending()
                        if self.config_manager.fetch_and_sync():
                            self._apply_config_updates()
                    sync_counter = 0

                # Live periodic refresh
                self._render_dashboard()
            except KeyboardInterrupt:
                break

        self.shutdown()

    def stop(self) -> None:
        self.running = False

    def shutdown(self) -> None:
        logger.info("Shutting down FarLink Agent...")
        self.running = False
        self.heartbeat_worker.stop()
        self.command_worker.stop()
        self.button_handler.cleanup()
        logger.info("FarLink Agent shutdown complete.")


def handle_signals(agent: FarlinkAgent):
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}. Terminating...")
        agent.stop()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    agent = FarlinkAgent()
    handle_signals(agent)
    agent.start()


if __name__ == "__main__":
    main()
