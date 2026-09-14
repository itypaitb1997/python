"""Device identity and hardware information handling."""
import uuid
import secrets
import string
from typing import Optional
from app.database import Database, get_utc_now



def generate_claim_code(length: int = 8) -> str:
    """Generate a short user-friendly claim code (e.g. FL-A8X3-9K2)."""
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"FL-{raw[:4]}-{raw[4:]}"


def get_mac_address() -> str:
    """Retrieve primary network MAC address with fallback."""
    try:
        import psutil
        for interface, addrs in psutil.net_if_addrs().items():
            if interface.startswith(("eth", "en", "wlan")):
                for addr in addrs:
                    if addr.family == psutil.AF_LINK or getattr(addr, "address", None):
                        mac = addr.address
                        if mac and len(mac.split(":")) == 6 and mac != "00:00:00:00:00:00":
                            return mac
    except ImportError:
        pass

    # Standard library fallback
    node = uuid.getnode()
    mac_hex = f"{node:012x}"
    return ":".join(mac_hex[i:i+2] for i in range(0, 12, 2))



class DeviceIdentity:
    def __init__(self, db: Database):
        self.db = db
        self.device_uuid: str = self._get_or_create_state("device_uuid", lambda: str(uuid.uuid4()))
        self.claim_code: str = self._get_or_create_state("claim_code", generate_claim_code)
        self.mac_address: str = get_mac_address()

    def _get_or_create_state(self, key: str, default_fn) -> str:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM device_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return str(row["value"])
            new_value = default_fn()
            cursor.execute(
                "INSERT INTO device_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, new_value, get_utc_now()),
            )
            return str(new_value)

    def get_token(self) -> Optional[str]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM device_state WHERE key = 'device_token'")
            row = cursor.fetchone()
            return str(row["value"]) if row else None

    def set_token(self, token: str) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO device_state (key, value, updated_at) VALUES ('device_token', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (token, get_utc_now()),
            )

    def get_status(self) -> str:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM device_state WHERE key = 'device_status'")
            row = cursor.fetchone()
            return str(row["value"]) if row else "PENDING"

    def set_status(self, status: str) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO device_state (key, value, updated_at) VALUES ('device_status', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (status, get_utc_now()),
            )
