"""Device authentication and registration management."""
from typing import Dict, Any, Optional
from app.api_client import ApiClient
from app.device_identity import DeviceIdentity
from app.logger import setup_logger
from app.constants import DeviceStatus

logger = setup_logger("auth")


class AuthManager:
    def __init__(self, api_client: ApiClient, identity: DeviceIdentity):
        self.api_client = api_client
        self.identity = identity
        # Load persisted token if available
        token = self.identity.get_token()
        if token:
            self.api_client.set_token(token)

    def register_device(self, agent_version: str = "1.0.0") -> bool:
        """Register device and obtain or verify registration status."""
        from app.config import config
        payload = {
            "device_uuid": self.identity.device_uuid,
            "claim_code": self.identity.claim_code,
            "mac_address": self.identity.mac_address,
            "agent_version": agent_version,
            "type": config.device_type,
            "mode": config.device_mode,
        }
        try:
            resp = self.api_client.post("devices/register", json=payload, max_retries=1)
            if resp.status_code in (200, 201):
                data = resp.json()
                status = data.get("status", DeviceStatus.PENDING.value)
                token = data.get("token")
                if token:
                    self.identity.set_token(token)
                    self.api_client.set_token(token)
                self.identity.set_status(status)
                logger.info(f"Device registered successfully. Status: {status}")
                return True
            else:
                self.api_client.is_connected = False
                logger.warning(f"Registration API returned HTTP {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            self.api_client.is_connected = False
            logger.info(
                f"[OFFLINE MODE] Server unreachable ({e}). Agent running cleanly in standalone offline mode."
            )
            return False

    def is_authenticated(self) -> bool:
        return bool(self.identity.get_token())
