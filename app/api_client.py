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

    def set_token(self, token: Optional[str]) -> None:
        self._token = token
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            self.session.headers.pop("Authorization", None)

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
                return response
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning(
                    f"HTTP {method} to {endpoint} failed (attempt {attempt}/{max_retries}): {e}"
                )
                if attempt == max_retries:
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
