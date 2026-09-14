"""Environment and Application Configuration."""
import os
from dataclasses import dataclass
from app.constants import (
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_PIN_START,
    DEFAULT_PIN_RESET,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass




@dataclass
class AppConfig:
    api_url: str = os.getenv("FARLINK_API_URL", "http://localhost:3000/api")
    db_path: str = os.getenv("FARLINK_DB_PATH", "farlink.db")
    log_path: str = os.getenv("FARLINK_LOG_PATH", "farlink.log")
    log_level: str = os.getenv("FARLINK_LOG_LEVEL", "INFO")
    heartbeat_interval: int = int(os.getenv("FARLINK_HEARTBEAT_INTERVAL", str(DEFAULT_HEARTBEAT_INTERVAL)))
    http_timeout: int = int(os.getenv("FARLINK_HTTP_TIMEOUT", str(DEFAULT_HTTP_TIMEOUT)))
    pin_start: int = int(os.getenv("FARLINK_PIN_START", str(DEFAULT_PIN_START)))
    pin_reset: int = int(os.getenv("FARLINK_PIN_RESET", str(DEFAULT_PIN_RESET)))


config = AppConfig()
