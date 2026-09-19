"""Test runner orchestrating real speed tests, iPerf, and network diagnostics."""
import time
import uuid
import requests
from typing import Dict, Any, Optional
from app.database import get_utc_now
from app.iperf_runner import IperfRunner
from app.network_diagnostics import NetworkDiagnostics
from app.logger import setup_logger

logger = setup_logger("test_runner")


class TestRunner:
    def __init__(self):
        self.iperf = IperfRunner()

    def _measure_http_bandwidth(self) -> Dict[str, Optional[float]]:
        """Perform real HTTP download and upload bandwidth measurement without dummy numbers."""
        dl_mbps = None
        ul_mbps = None

        # 1. Measure Download (Stream 5MB test payload)
        dl_targets = [
            "https://speed.cloudflare.com/__down?bytes=5000000",
            "https://httpbin.org/bytes/3000000",
        ]
        for url in dl_targets:
            try:
                t0 = time.time()
                resp = requests.get(url, timeout=6, stream=True)
                if resp.status_code == 200:
                    total_bytes = 0
                    for chunk in resp.iter_content(chunk_size=65536):
                        total_bytes += len(chunk)
                    elapsed = time.time() - t0
                    if elapsed > 0.05 and total_bytes > 0:
                        dl_mbps = round((total_bytes * 8) / (elapsed * 1_000_000), 2)
                        break
            except Exception as e:
                logger.debug(f"Download measurement attempt failed on {url}: {e}")

        # 2. Measure Upload (POST 1MB test chunk)
        ul_targets = [
            "https://speed.cloudflare.com/__up",
            "https://httpbin.org/post",
        ]
        payload = b"0" * 1_000_000
        for url in ul_targets:
            try:
                t0 = time.time()
                resp = requests.post(url, data=payload, timeout=6)
                elapsed = time.time() - t0
                if resp.status_code == 200 and elapsed > 0.05:
                    ul_mbps = round((len(payload) * 8) / (elapsed * 1_000_000), 2)
                    break
            except Exception as e:
                logger.debug(f"Upload measurement attempt failed on {url}: {e}")

        return {"download_mbps": dl_mbps, "upload_mbps": ul_mbps}

    def run_speed_test(self, server_ip: Optional[str] = None) -> Dict[str, Any]:
        """Run network speed test (or point-to-point iPerf if server_ip given) with real data."""
        started_at = get_utc_now()
        start_ts = time.time()
        test_id = str(uuid.uuid4())

        # Perform ping latency check first
        target_host = server_ip if server_ip else "8.8.8.8"
        diag = NetworkDiagnostics.ping_latency(target_host, count=3)
        latency = diag.get("latency_ms")
        jitter_ms = diag.get("jitter_ms")
        packet_loss = diag.get("loss_percent", 0.0)

        download_mbps = None
        upload_mbps = None

        if server_ip:
            # Point-to-point iPerf3 test
            res = self.iperf.run_client(server_ip=server_ip, duration=5)
            download_mbps = res.get("bandwidth_mbps")
            upload_mbps = download_mbps
            if res.get("jitter_ms") is not None:
                jitter_ms = res.get("jitter_ms")
            if res.get("packet_loss") is not None:
                packet_loss = res.get("packet_loss")
        else:
            # Standalone real HTTP speed test
            speed = self._measure_http_bandwidth()
            download_mbps = speed.get("download_mbps")
            upload_mbps = speed.get("upload_mbps")

        finished_at = get_utc_now()

        return {
            "id": test_id,
            "test_type": "iperf" if server_ip else "network_check",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(time.time() - start_ts, 2),
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "latency_ms": latency,
            "jitter_ms": jitter_ms,
            "packet_loss": packet_loss,
        }
