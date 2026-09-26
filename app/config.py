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
    load_dotenv(dotenv_path=ENV_PATH, override=True)
except ImportError:
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.split("#")[0].strip().strip("'\"")
                    os.environ[k] = v


def _get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is not None:
        try:
            return int(str(val).split("#")[0].strip())
        except (ValueError, TypeError):
            pass
    return default


def _get_env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    if val is not None:
        clean = str(val).split("#")[0].strip().strip("'\"")
        if clean:
            return clean
    return default


@dataclass
class AppConfig:
    api_url: str = _get_env_str("FARLINK_API_URL", "http://127.0.0.1:5000/api")
    db_path: str = _get_env_str("FARLINK_DB_PATH", "farlink_agent.db")
    log_path: str = _get_env_str("FARLINK_LOG_PATH", "farlink_agent.log")
    log_level: str = _get_env_str("FARLINK_LOG_LEVEL", "INFO")
    heartbeat_interval: int = _get_env_int("FARLINK_HEARTBEAT_INTERVAL", DEFAULT_HEARTBEAT_INTERVAL)
    http_timeout: int = _get_env_int("FARLINK_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT)
    pin_start: int = _get_env_int("FARLINK_PIN_START", DEFAULT_PIN_START)
    pin_reset: int = _get_env_int("FARLINK_PIN_RESET", DEFAULT_PIN_RESET)
    device_type: str = _get_env_str("FARLINK_DEVICE_TYPE", "FarLink Go")
    device_mode: str = _get_env_str("FARLINK_DEVICE_MODE", "Standalone")


config = AppConfig()

