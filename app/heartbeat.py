"""Heartbeat worker sending regular health updates to cloud backend."""
import threading
import time
from typing import Optional
from app.api_client import ApiClient
from app.device_identity import DeviceIdentity
from app.health_monitor import HealthMonitor
from app.logger import setup_logger
from app.constants import DEFAULT_HEARTBEAT_INTERVAL, DEFAULT_AGENT_VERSION

logger = setup_logger("heartbeat")


class HeartbeatWorker(threading.Thread):
    def __init__(
        self,
        api_client: ApiClient,
        identity: DeviceIdentity,
        health_monitor: HealthMonitor,
        interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    ):
        super().__init__(daemon=True, name="HeartbeatWorker")
        self.api_client = api_client
        self.identity = identity
        self.health_monitor = health_monitor
        self.interval = interval
        self._stop_event = threading.Event()
        self.last_test_at: Optional[str] = None
        self.config_version: int = 1
        self.master_ip: Optional[str] = None
        self.master_connected: Optional[bool] = None
        self.master_latency_ms: Optional[float] = None

    def stop(self) -> None:
        self._stop_event.set()

    def set_interval(self, new_interval: int) -> None:
        """Update heartbeat interval dynamically."""
        if new_interval > 0 and new_interval != self.interval:
            logger.info(f"Heartbeat interval updated: {self.interval}s -> {new_interval}s")
            self.interval = new_interval

    def run(self) -> None:
        logger.info(f"Heartbeat worker started (interval: {self.interval}s)")
        while not self._stop_event.is_set():
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.debug(f"[HEARTBEAT] Offline state: Server unreachable ({e})")

            # Sleep with responsive stop check
            if self._stop_event.wait(timeout=self.interval):
                break
        logger.info("Heartbeat worker stopped")

    def send_heartbeat(self) -> bool:
        metrics = self.health_monitor.get_metrics()
        payload = {
            "device_uuid": self.identity.device_uuid,
            "agent_version": DEFAULT_AGENT_VERSION,
            "config_version": self.config_version,
            "registration_status": self.identity.get_status(),
            "connection_status": "ONLINE" if self.api_client.is_connected else "OFFLINE",
            "ip_address": metrics["ip_address"],
            "mac_address": self.identity.mac_address,
            "cpu_usage": metrics["cpu_usage"],
            "ram_usage": metrics["ram_usage"],
            "disk_usage": metrics["disk_usage"],
            "temperature": metrics["temperature"],
            "uptime": metrics["uptime"],
            "last_test_at": self.last_test_at,
            "os_version": metrics["os_version"],
            "service_status": "RUNNING",
            "master_ip": self.master_ip,
            "master_connected": self.master_connected,
            "master_latency_ms": self.master_latency_ms,
        }

        try:
            resp = self.api_client.post("agent/heartbeat", json=payload, max_retries=3)
            if resp.status_code in (200, 201):
                logger.debug("Heartbeat successfully sent")
                return True
            else:
                logger.debug(f"Heartbeat rejected: HTTP {resp.status_code}")
                return False
        except Exception as e:
            logger.debug(f"[HEARTBEAT] Cloud server unreachable ({e}). Postponing heartbeat.")
            return False
