"""HTTP API Client with timeout, retries, and token authentication."""
import time
from typing import Any, Dict, Optional
from app.logger import setup_logger
from app.constants import DEFAULT_INITIAL_RETRY_DELAY, DEFAULT_MAX_RETRIES

try:
    import requests
except ImportError:
    class DummySession:
        headers = {}
        def request(self, *args, **kwargs):
            raise NotImplementedError("requests package is not installed.")
    requests = type("DummyRequests", (), {
        "Session": DummySession,
        "ConnectionError": IOError,
        "Timeout": TimeoutError,
        "Response": object
    })()

logger = setup_logger("api_client")



class ApiClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self._token: Optional[str] = None
        self._device_uuid: Optional[str] = None
        self.is_connected: bool = False
        self.last_error: Optional[str] = None
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            retry_strategy = Retry(
                total=2,
                backoff_factor=0.3,
                status_forcelist=[502, 503, 504],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
        except Exception:
            pass

    def set_device_uuid(self, device_uuid: Optional[str]) -> None:
        self._device_uuid = device_uuid
        if device_uuid:
            self.session.headers.update({"X-Device-UUID": device_uuid})
        else:
            self.session.headers.pop("X-Device-UUID", None)

    def set_token(self, token: Optional[str]) -> None:
        self._token = token
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            self.session.headers.pop("Authorization", None)

    def check_connection(self, timeout: int = 5) -> bool:
        """Quick health probe to check if cloud server is reachable."""
        url = f"{self.base_url}/health"
        try:
            resp = self.session.get(url, timeout=timeout)
            self.is_connected = (resp.status_code in (200, 204, 404))  # Any response means host reached
            self.last_error = None if self.is_connected else f"HTTP {resp.status_code}"
            return self.is_connected
        except (requests.ConnectionError, requests.Timeout) as e:
            self.is_connected = False
            self.last_error = "Server unreachable"
            return False
        except Exception as e:
            self.is_connected = False
            self.last_error = str(e)
            return False

    def request_with_retry(
        self,
        method: str,
        endpoint: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs
    ) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        kwargs.setdefault("timeout", self.timeout)
        delay = DEFAULT_INITIAL_RETRY_DELAY

        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                self.is_connected = True
                self.last_error = None
                return response
            except (requests.ConnectionError, requests.Timeout) as e:
                self.is_connected = False
                self.last_error = f"Connection error: {e}"
                if attempt == max_retries:
                    logger.debug(f"[OFFLINE] HTTP {method} to {endpoint} failed (attempt {attempt}/{max_retries}): {e}")
                    raise
                time.sleep(delay)
                delay *= 2  # Exponential backoff
        raise RuntimeError("Unexpected end of retry loop")

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request_with_retry("GET", endpoint, **kwargs)

    def post(self, endpoint: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> requests.Response:
        return self.request_with_retry("POST", endpoint, json=json, **kwargs)

    def put(self, endpoint: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> requests.Response:
        return self.request_with_retry("PUT", endpoint, json=json, **kwargs)

    def patch(self, endpoint: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> requests.Response:
        return self.request_with_retry("PATCH", endpoint, json=json, **kwargs)

