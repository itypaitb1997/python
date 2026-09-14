"""Configuration manager supporting atomic updates, versioning, and rollback."""
import json
from typing import Any, Dict, Optional
from app.api_client import ApiClient
from app.database import Database, get_utc_now
from app.logger import setup_logger

logger = setup_logger("config_manager")


class ConfigManager:
    def __init__(self, db: Database, api_client: ApiClient):
        self.db = db
        self.api_client = api_client
        self.active_config: Dict[str, Any] = self._load_active_config()

    def _load_active_config(self) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT config_json FROM local_config WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row["config_json"])
                except json.JSONDecodeError:
                    pass
        # Default baseline config
        return {
            "version": 1,
            "heartbeat_interval": 60,
            "sync_interval": 60,
            "iperf_duration": 10,
            "iperf_streams": 1,
            "test_mode": "standalone",
        }

    def get_active_version(self) -> int:
        return int(self.active_config.get("version", 1))

    def validate_config(self, config_data: Dict[str, Any]) -> bool:
        """Validate configuration structure before applying."""
        required_keys = ["version"]
        for key in required_keys:
            if key not in config_data:
                logger.error(f"Invalid config: missing key '{key}'")
                return False
        return True

    def apply_config(self, new_config: Dict[str, Any]) -> bool:
        """Atomically persist and apply new configuration."""
        if not self.validate_config(new_config):
            return False

        version = int(new_config["version"])
        config_json = json.dumps(new_config)

        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Deactivate current active config
                cursor.execute("UPDATE local_config SET is_active = 0")
                # Insert or update new version
                cursor.execute(
                    """
                    INSERT INTO local_config (version, config_json, is_active, created_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(version) DO UPDATE SET
                        config_json = excluded.config_json,
                        is_active = 1
                    """,
                    (version, config_json, get_utc_now()),
                )
            self.active_config = new_config
            logger.info(f"Successfully applied configuration version {version}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply config version {version}: {e}")
            return False

    def rollback(self) -> bool:
        """Roll back to previous valid configuration if available."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT version, config_json FROM local_config ORDER BY version DESC"
            )
            rows = cursor.fetchall()
            if len(rows) > 1:
                # Pick the second latest
                prev_row = rows[1]
                prev_version = prev_row["version"]
                cursor.execute("UPDATE local_config SET is_active = 0")
                cursor.execute("UPDATE local_config SET is_active = 1 WHERE version = ?", (prev_version,))
                self.active_config = json.loads(prev_row["config_json"])
                logger.info(f"Rolled back to configuration version {prev_version}")
                return True
        logger.warning("No previous configuration version available for rollback")
        return False

    def fetch_and_sync(self) -> bool:
        """Fetch latest configuration from backend and apply if newer."""
        try:
            resp = self.api_client.get("agent/config")
            if resp.status_code == 200:
                remote_cfg = resp.json()
                remote_version = remote_cfg.get("version", 0)
                if remote_version > self.get_active_version():
                    if self.apply_config(remote_cfg):
                        # Send ack to server
                        self.api_client.post("agent/config/ack", json={"version": remote_version})
                        return True
            return False
        except Exception as e:
            logger.warning(f"Error fetching remote configuration: {e}")
            return False
