"""Main entry point for FarLink Agent."""
import sys
import time
import signal
from typing import Dict, Any
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
        self.auth = AuthManager(self.api_client, self.identity)
        self.health = HealthMonitor()
        self.test_runner = TestRunner()
        self.sync_manager = SyncManager(self.db, self.api_client)
        self.config_manager = ConfigManager(self.db, self.api_client)
        self.lcd = LCDDisplay()

        # Remote command worker
        self.command_worker = CommandWorker(self.api_client, self.db)
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

    def _register_commands(self) -> None:
        self.command_worker.register_handler("SYNC_CONFIG", self._sync_config_command)
        self.command_worker.register_handler("RUN_TEST", lambda p: self.run_test_command(p))
        self.command_worker.register_handler("SYNC_DATA", self._sync_data_command)
        self.command_worker.register_handler("RESTART_AGENT", lambda p: self.stop())

    def _render_dashboard(self, last_test: Optional[Dict[str, Any]] = None) -> None:
        """Render live terminal dashboard tables."""
        try:
            CLIDisplay.render(
                identity=self.identity,
                health=self.health,
                db=self.db,
                active_config=self.config_manager.active_config,
                api_url=config.api_url,
                last_test=last_test,
            )
        except Exception as e:
            logger.debug(f"CLI display render error: {e}")

    def on_start_button(self) -> None:
        logger.info("Start test triggered by physical button")
        self.lcd.display_status("Starting Test...", "Please wait")
        result = self.test_runner.run_speed_test()
        self.sync_manager.enqueue_result(result)
        self.heartbeat_worker.last_test_at = result["finished_at"]
        self.lcd.show_test_result(
            dl_mbps=result["download_mbps"],
            ul_mbps=result["upload_mbps"],
            latency=result.get("latency_ms"),
        )
        self._render_dashboard(last_test=result)

    def on_reset_button(self) -> None:
        logger.info("Reset triggered by physical button")
        self.lcd.display_status("Device Resetting", "Re-init network")
        # Trigger network diagnostic
        diag = NetworkDiagnostics.run_full_diagnostics()
        status_line = "Net: OK" if diag.get("internet_connected") else "Net: Offline"
        self.lcd.display_status(f"Claim: {self.identity.claim_code}", status_line)
        self._render_dashboard()

    def run_test_command(self, payload: Dict[str, Any]) -> bool:
        server_ip = payload.get("server_ip")
        res = self.test_runner.run_speed_test(server_ip=server_ip)
        self.sync_manager.enqueue_result(res)
        self.heartbeat_worker.last_test_at = res["finished_at"]
        self._render_dashboard(last_test=res)
        return True

    def start(self) -> None:
        logger.info(f"Agent Device UUID: {self.identity.device_uuid}")
        logger.info(f"Agent Claim Code: {self.identity.claim_code}")

        self.lcd.display_status(
            f"ID:{self.identity.claim_code[:12]}",
            f"Stat:{self.identity.get_status()}"
        )

        # Attempt initial registration
        self.auth.register_device()

        # Start workers
        self.heartbeat_worker.start()
        self.command_worker.start()

        # Check for remote config on boot
        if self.config_manager.fetch_and_sync():
            self._apply_config_updates()

        # Initial dashboard render
        self._render_dashboard()

        sync_counter = 0
        while self.running:
            try:
                time.sleep(5)
                sync_counter += 5
                active_cfg = self.config_manager.active_config
                sync_interval = int(active_cfg.get("sync_interval", 60))

                if sync_counter >= sync_interval:
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
