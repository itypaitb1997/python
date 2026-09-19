"""Main entry point for FarLink Agent."""
import os
import sys
import time
import signal
import threading
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

        cfg = self.config_manager.active_config
        self.device_type = cfg.get("type") or cfg.get("device_type") or config.device_type
        self.device_mode = cfg.get("mode") or cfg.get("device_mode") or config.device_mode
        self.master_ip: Optional[str] = cfg.get("master_ip") or os.getenv("FARLINK_MASTER_IP")
        self.master_connected: bool = False
        self.master_latency_ms: Optional[float] = None
        if self.master_ip:
            self.heartbeat_worker.master_ip = self.master_ip

        self.iperf_server_proc = None
        if self.device_type == "FarLink Edge" and self.device_mode == "Slave":
            logger.info("FarLink Edge Slave mode detected. Starting background iPerf3 server...")
            self.iperf_server_proc = self.test_runner.iperf.start_server_process()

        self.server_connected: bool = False
        self.latest_notification: str = f"Initializing {self.device_type} Agent ({self.device_mode})..."
        self.running = True

    def _check_master_connectivity(self) -> None:
        """Probe connectivity to FarLink Go Master when running in Slave mode."""
        if self.device_mode != "Slave":
            return

        cfg_master = self.config_manager.active_config.get("master_ip") or os.getenv("FARLINK_MASTER_IP")
        if cfg_master:
            self.master_ip = cfg_master
        elif not self.master_ip:
            gw = NetworkDiagnostics.get_default_gateway()
            if gw:
                self.master_ip = gw

        if self.master_ip:
            diag = NetworkDiagnostics.ping_latency(self.master_ip)
            lat = diag.get("latency_ms")
            self.master_connected = bool(lat is not None and lat < 900)
            self.master_latency_ms = lat
            self.heartbeat_worker.master_ip = self.master_ip
            self.heartbeat_worker.master_connected = self.master_connected
            self.heartbeat_worker.master_latency_ms = lat

    def _apply_config_updates(self) -> None:
        """Apply active config updates to running workers."""
        cfg = self.config_manager.active_config
        hb_interval = int(cfg.get("heartbeat_interval", config.heartbeat_interval))
        self.heartbeat_worker.set_interval(hb_interval)
        self.heartbeat_worker.config_version = self.config_manager.get_active_version()

        # Update dynamic device type and mode from remote configuration
        new_type = cfg.get("type") or cfg.get("device_type")
        new_mode = cfg.get("mode") or cfg.get("device_mode")
        if new_type:
            self.device_type = new_type
        if new_mode:
            self.device_mode = new_mode

        if "master_ip" in cfg:
            self.master_ip = cfg.get("master_ip")
            self.heartbeat_worker.master_ip = self.master_ip
            self._check_master_connectivity()

        # Manage iPerf3 server daemon if mode switched
        if self.device_type == "FarLink Edge" and self.device_mode == "Slave":
            if not self.iperf_server_proc:
                logger.info("FarLink Edge Slave active: starting iPerf3 server daemon...")
                self.iperf_server_proc = self.test_runner.iperf.start_server_process()
        else:
            if self.iperf_server_proc:
                logger.info("Stopping iPerf3 server daemon (device is no longer Edge Slave)...")
                try:
                    self.iperf_server_proc.terminate()
                except Exception:
                    pass
                self.iperf_server_proc = None

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
            import subprocess
            import platform
            time.sleep(2.0)
            logger.info("Restarting agent process...")
            self.shutdown()
            if platform.system() == "Linux":
                try:
                    cmd = ["systemctl", "restart", "farlink-agent"] if os.geteuid() == 0 else ["sudo", "-n", "systemctl", "restart", "farlink-agent"]
                    subprocess.run(cmd, timeout=5)
                except Exception:
                    pass
            os._exit(0)
        import threading
        threading.Thread(target=_delayed_stop, daemon=True).start()
        return True

    def _reboot_device_command(self, payload: Dict[str, Any]) -> bool:
        logger.info("REBOOT_DEVICE command received from web: scheduling system reboot")
        self.latest_notification = "System reboot requested via Web. Rebooting now..."
        self._render_dashboard()
        def _delayed_reboot():
            import time
            import os
            import subprocess
            import platform
            time.sleep(2.0)
            logger.info("Executing system reboot...")
            self.shutdown()
            if platform.system() == "Linux":
                try:
                    cmd = ["reboot"] if os.geteuid() == 0 else ["sudo", "-n", "reboot"]
                    subprocess.run(cmd, timeout=5)
                except Exception:
                    pass
            os._exit(0)
        import threading
        threading.Thread(target=_delayed_reboot, daemon=True).start()
        return True

    def _register_commands(self) -> None:
        self.command_worker.register_handler("SYNC_CONFIG", self._sync_config_command)
        self.command_worker.register_handler("RUN_TEST", lambda p: self.run_test_command(p))
        self.command_worker.register_handler("SYNC_DATA", self._sync_data_command)
        self.command_worker.register_handler("UPLOAD_LOG", self._upload_log_command)
        self.command_worker.register_handler("RESTART_AGENT", self._restart_agent_command)
        self.command_worker.register_handler("REBOOT_DEVICE", self._reboot_device_command)

    def _render_dashboard(self, last_test: Optional[Dict[str, Any]] = None, test_running: bool = False) -> None:
        """Render and continuously maintain GUI on LCD/Framebuffer and terminal."""
        try:
            pending_count = self.sync_manager.get_pending_count()
            diag = NetworkDiagnostics.run_full_diagnostics()
            conn = diag.get("connection_type") or NetworkDiagnostics.get_connection_type()

            if last_test is None:
                last_test = self.db.get_latest_test_result()

            if last_test:
                dl = last_test.get("download_mbps")
                ul = last_test.get("upload_mbps")
                lat = last_test.get("latency_ms")
                jit = last_test.get("jitter_ms")
                rtc_t = last_test.get("rtc_time") or last_test.get("finished_at")
            else:
                dl = None
                ul = None
                lat = diag.get("internet_latency_ms")
                jit = diag.get("jitter_ms")
                rtc_t = None

            if test_running:
                status_text = "Running test..."
                status_color = "#38bdf8"
            elif last_test:
                status_text = "Test complete"
                status_color = "#22c55e"
            elif self.server_connected:
                status_text = "Ready"
                status_color = "#22c55e"
            else:
                status_text = "Offline"
                status_color = "#f59e0b"

            # 1. ALWAYS redraw and maintain the graphical GUI on LCD / Framebuffer
            self.lcd.update_dashboard(
                dl_mbps=dl,
                ul_mbps=ul,
                latency_ms=lat,
                jitter_ms=jit,
                device_code=self.identity.claim_code,
                status_text=status_text,
                status_color=status_color,
                conn_type=conn.get("type", "Ethernet"),
                rtc_time=rtc_t,
            )

            # 2. Render CLI (suppressing direct /dev/tty1 writes when graphical framebuffer is active)
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
                master_ip=self.master_ip,
                master_connected=self.master_connected,
                master_latency_ms=self.master_latency_ms,
                suppress_console=self.lcd.is_hardware_available,
            )
        except Exception as e:
            logger.debug(f"Display render error: {e}")

    def on_start_button(self) -> None:
        try:
            logger.info("Start test triggered")
            self.latest_notification = "Running diagnostic speed test... Please wait."
            conn = NetworkDiagnostics.get_connection_type()
            self.lcd.update_dashboard(
                device_code=self.identity.claim_code,
                status_text="Running test...",
                status_color="#38bdf8",
                conn_type=conn.get("type", "Ethernet"),
            )
            self._render_dashboard(test_running=True)

            result = self.test_runner.run_speed_test()
            self.sync_manager.enqueue_result(result)
            
            # Try syncing if online
            synced = self.sync_manager.sync_pending()
            self.server_connected = self.api_client.is_connected
            pending_cnt = self.sync_manager.get_pending_count()

            dl_val = result.get('download_mbps')
            dl_text = f"DL: {dl_val:.1f} Mbps" if dl_val is not None else "DL: -"
            if self.server_connected:
                self.latest_notification = f"Test finished ({dl_text}). Synced with cloud."
            else:
                self.latest_notification = f"Test finished ({dl_text}). Saved locally ({pending_cnt} queued)."

            self.heartbeat_worker.last_test_at = result["finished_at"]
            self.lcd.show_test_result(
                dl_mbps=result.get("download_mbps"),
                ul_mbps=result.get("upload_mbps"),
                latency=result.get("latency_ms"),
                jitter=result.get("jitter_ms"),
                device_code=self.identity.claim_code,
                status_text="Test complete",
                conn_type=conn.get("type", "Ethernet"),
            )
            self._render_dashboard(last_test=result, test_running=False)
        except Exception as e:
            logger.error(f"Error executing speed test: {e}", exc_info=True)
            self.latest_notification = f"Test warning: {e}"
            self._render_dashboard(test_running=False)

    def on_reset_button(self) -> None:
        logger.info("Reset triggered by physical button")
        self.latest_notification = "Re-evaluating network diagnostics & connection..."
        conn = NetworkDiagnostics.get_connection_type()
        self.lcd.update_dashboard(
            device_code=self.identity.claim_code,
            status_text="Resetting...",
            status_color="#f59e0b",
            conn_type=conn.get("type", "Ethernet"),
        )
        
        # Trigger network diagnostic and probe server
        diag = NetworkDiagnostics.run_full_diagnostics()
        self.server_connected = self.api_client.check_connection(timeout=2)

        if self.server_connected:
            srv_msg = "Server: Connected"
            self.latest_notification = "Network re-checked: Internet & FarLink Cloud ONLINE."
            status_text = "Online"
            status_color = "#22c55e"
        else:
            srv_msg = "Server: Disconnected"
            self.latest_notification = "Network re-checked: Standalone offline mode active."
            status_text = "Offline"
            status_color = "#f59e0b"

        self.lcd.update_dashboard(
            latency_ms=diag.get("internet_latency_ms"),
            jitter_ms=diag.get("jitter_ms"),
            device_code=self.identity.claim_code,
            status_text=status_text,
            status_color=status_color,
            conn_type=diag.get("connection_type", {}).get("type", "Ethernet"),
        )
        self._render_dashboard()

    def run_test_command(self, payload: Dict[str, Any]) -> bool:
        server_ip = payload.get("server_ip")
        conn = NetworkDiagnostics.get_connection_type()
        self.lcd.update_dashboard(
            device_code=self.identity.claim_code,
            status_text="Running test...",
            status_color="#38bdf8",
            conn_type=conn.get("type", "Ethernet"),
        )
        res = self.test_runner.run_speed_test(server_ip=server_ip)
        self.sync_manager.enqueue_result(res)
        self.sync_manager.sync_pending()
        self.server_connected = self.api_client.is_connected
        self.heartbeat_worker.last_test_at = res["finished_at"]
        dl_val = res.get('download_mbps')
        dl_text = f"DL: {dl_val:.1f} Mbps" if dl_val is not None else "DL: -"
        self.latest_notification = f"Remote test completed ({dl_text})."
        self.lcd.show_test_result(
            dl_mbps=res.get("download_mbps"),
            ul_mbps=res.get("upload_mbps"),
            latency=res.get("latency_ms"),
            jitter=res.get("jitter_ms"),
            device_code=self.identity.claim_code,
            status_text="Test complete",
            conn_type=conn.get("type", "Ethernet"),
        )
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

        # Real initial network diagnostics and connection detection
        diag = NetworkDiagnostics.run_full_diagnostics()
        conn = diag.get("connection_type") or NetworkDiagnostics.get_connection_type()
        last_test = self.db.get_latest_test_result()

        dl_mbps = last_test.get("download_mbps") if last_test else None
        ul_mbps = last_test.get("upload_mbps") if last_test else None
        lat = last_test.get("latency_ms") if last_test else diag.get("internet_latency_ms")
        jit = last_test.get("jitter_ms") if last_test else diag.get("jitter_ms")

        self.lcd.update_dashboard(
            dl_mbps=dl_mbps,
            ul_mbps=ul_mbps,
            latency_ms=lat,
            jitter_ms=jit,
            device_code=self.identity.claim_code,
            status_text="Ready" if self.server_connected else "Offline",
            status_color="#22c55e" if self.server_connected else "#f59e0b",
            conn_type=conn.get("type", "Ethernet"),
        )

        # Start workers
        self.heartbeat_worker.start()
        self.command_worker.start()

        # Check for remote config on boot if connected
        if self.server_connected and self.config_manager.fetch_and_sync():
            self._apply_config_updates()

        # Initial dashboard render
        self._check_master_connectivity()
        self._render_dashboard(last_test=last_test)

        # Trigger automatic initial test so download & upload appear on startup without needing button press
        threading.Thread(target=self.on_start_button, daemon=True).start()

        sync_counter = 0
        connection_check_counter = 0
        master_check_counter = 0

        while self.running:
            try:
                time.sleep(3)
                sync_counter += 3
                connection_check_counter += 3
                master_check_counter += 3

                # Periodically probe master reachability in Slave mode
                if master_check_counter >= 6:
                    self._check_master_connectivity()
                    master_check_counter = 0

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
        if getattr(self, "iperf_server_proc", None):
            try:
                self.iperf_server_proc.terminate()
                self.iperf_server_proc = None
            except Exception:
                pass
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
