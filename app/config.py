"""Environment and Application Configuration."""
import os
from dataclasses import dataclass
from app.constants import (
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_PIN_START,
    DEFAULT_PIN_RESET,
)

from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_PATH)
except ImportError:
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v




@dataclass
class AppConfig:
    api_url: str = os.getenv("FARLINK_API_URL", "http://192.168.1.2:5000/api")
    db_path: str = os.getenv("FARLINK_DB_PATH", "farlink.db")
    log_path: str = os.getenv("FARLINK_LOG_PATH", "farlink.log")
    log_level: str = os.getenv("FARLINK_LOG_LEVEL", "INFO")
    heartbeat_interval: int = int(os.getenv("FARLINK_HEARTBEAT_INTERVAL", str(DEFAULT_HEARTBEAT_INTERVAL)))
    http_timeout: int = int(os.getenv("FARLINK_HTTP_TIMEOUT", str(DEFAULT_HTTP_TIMEOUT)))
    pin_start: int = int(os.getenv("FARLINK_PIN_START", str(DEFAULT_PIN_START)))
    pin_reset: int = int(os.getenv("FARLINK_PIN_RESET", str(DEFAULT_PIN_RESET)))
    device_type: str = os.getenv("FARLINK_DEVICE_TYPE", "FarLink Go")
    device_mode: str = os.getenv("FARLINK_DEVICE_MODE", "Standalone")


config = AppConfig()
