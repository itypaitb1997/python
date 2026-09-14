"""Constants and Enums for FarLink Agent."""
from enum import Enum


class DeviceStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"
    ERROR = "ERROR"


class CommandStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


# Technical Defaults per GEMINI.md Section 23
DEFAULT_HEARTBEAT_INTERVAL = 60
DEFAULT_HTTP_TIMEOUT = 10
DEFAULT_INITIAL_RETRY_DELAY = 2.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_CONFIG_VERSION = 1
DEFAULT_AGENT_VERSION = "1.0.0"

# Button GPIO Pins (Active Low)
DEFAULT_PIN_START = 5
DEFAULT_PIN_RESET = 6
