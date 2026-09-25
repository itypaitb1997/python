"""Test runner orchestrating real speed tests, iPerf, and network diagnostics."""
import time
import uuid
import ssl
import urllib.request
from typing import Dict, Any, Optional
from app.config import config
from app.database import get_utc_now
from app.iperf_runner import IperfRunner
from app.network_diagnostics import NetworkDiagnostics
from app.logger import setup_logger

logger = setup_logger("test_runner")


class TestRunner:
    def __init__(self):
        self.iperf = IperfRunner()
        self._ssl_ctx = ssl._create_unverified_context()

    def _measure_http_bandwidth(self) -> Dict[str, Optional[float]]:
        """Perform real HTTP download and upload bandwidth measurement without dummy numbers."""
        dl_mbps = None
        ul_mbps = None

        headers = {
            "User-Agent": "FarLink-Agent/1.0 (Raspberry Pi; Linux)",
            "Accept": "*/*",
        }

        # 1. Measure Download
        dl_targets = [
            f"{config.api_url}/tests/speedtest/download?size=2500000",
            "https://speed.cloudflare.com/__down?bytes=2500000",
            "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js",
            "https://ajax.googleapis.com/ajax/libs/jquery/3.7.1/jquery.min.js",
            "https://code.jquery.com/jquery-3.7.1.min.js",
        ]

        for url in dl_targets:
            try:
                req = urllib.request.Request(url, headers=headers)
                t0 = time.time()
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    total_bytes = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                elapsed = time.time() - t0
                if elapsed > 0.02 and total_bytes > 10000:
                    dl_mbps = round((total_bytes * 8) / (elapsed * 1_000_000), 1)
                    logger.info(f"Real download measured via {url}: {dl_mbps} Mbps ({total_bytes} bytes in {elapsed:.2f}s)")
                    break
            except Exception as e:
                logger.debug(f"Download attempt failed on {url}: {e}")

        # 2. Measure Upload
        payload = b"0" * 500_000  # 500 KB test chunk
        ul_targets = [
            f"{config.api_url}/tests/speedtest/upload",
            "https://speed.cloudflare.com/__up",
            "https://httpbin.org/post",
        ]

        for url in ul_targets:
            try:
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                t0 = time.time()
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    resp.read(512)
                elapsed = time.time() - t0
                if elapsed > 0.02:
                    ul_mbps = round((len(payload) * 8) / (elapsed * 1_000_000), 1)
                    logger.info(f"Real upload measured via {url}: {ul_mbps} Mbps ({len(payload)} bytes in {elapsed:.2f}s)")
                    break
            except Exception as e:
                logger.debug(f"Upload attempt failed on {url}: {e}")

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
        conn = NetworkDiagnostics.get_connection_type()

        return {
            "id": test_id,
            "test_type": "iperf" if server_ip else "network_check",
            "started_at": started_at,
            "finished_at": finished_at,
            "rtc_time": started_at,
            "duration_seconds": round(time.time() - start_ts, 2),
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "latency_ms": latency,
            "jitter_ms": jitter_ms,
            "packet_loss": packet_loss,
            "connection_type": conn.get("type", "Ethernet"),
            "interface": conn.get("interface", "eth0"),
        }

    def run_edge_dual_test(
        self,
        master_ip: Optional[str] = None,
        iperf_duration: int = 5,
        iperf_streams: int = 1,
    ) -> Dict[str, Any]:
        """Dual-connection diagnostic for FarLink Edge:
        1. Connection to Master (iPerf3 bandwidth, latency, jitter, packet loss)
        2. Connection to Internet (ping latency, jitter, loss & HTTP bandwidth)
        """
        started_at = get_utc_now()
        start_ts = time.time()
        test_id = str(uuid.uuid4())

        # Resolve Master target if none provided
        target_master = master_ip
        if not target_master:
            gw = NetworkDiagnostics.get_default_gateway()
            if gw:
                target_master = gw

        # 1. Measure Connection to Master
        master_conn = {
            "target": target_master,
            "connected": False,
            "latency_ms": None,
            "jitter_ms": None,
            "packet_loss": None,
            "bandwidth_mbps": None,
        }
        if target_master:
            logger.info(f"[EDGE DUAL TEST] Testing Connection 1 (Master: {target_master})...")
            m_ping = NetworkDiagnostics.ping_latency(target_master, count=3)
            master_conn["latency_ms"] = m_ping.get("latency_ms")
            master_conn["jitter_ms"] = m_ping.get("jitter_ms")
            master_conn["packet_loss"] = m_ping.get("loss_percent", 0.0)

            # iPerf3 throughput to Master
            iperf_res = self.iperf.run_client(
                server_ip=target_master,
                duration=iperf_duration,
                streams=iperf_streams
            )
            master_conn["bandwidth_mbps"] = iperf_res.get("bandwidth_mbps")
            if iperf_res.get("jitter_ms") is not None:
                master_conn["jitter_ms"] = iperf_res.get("jitter_ms")
            if iperf_res.get("packet_loss") is not None:
                master_conn["packet_loss"] = iperf_res.get("packet_loss")
            master_conn["connected"] = bool(
                master_conn["latency_ms"] is not None or master_conn["bandwidth_mbps"] is not None
            )

        # 2. Measure Connection to Internet
        logger.info("[EDGE DUAL TEST] Testing Connection 2 (Internet: 8.8.8.8 & Web)...")
        net_ping = NetworkDiagnostics.ping_latency("8.8.8.8", count=3)
        inet_speed = self._measure_http_bandwidth()
        internet_conn = {
            "target": "8.8.8.8",
            "connected": bool(net_ping.get("latency_ms") is not None or inet_speed.get("download_mbps") is not None),
            "latency_ms": net_ping.get("latency_ms"),
            "jitter_ms": net_ping.get("jitter_ms"),
            "packet_loss": net_ping.get("loss_percent", 0.0),
            "download_mbps": inet_speed.get("download_mbps"),
            "upload_mbps": inet_speed.get("upload_mbps"),
        }

        finished_at = get_utc_now()

        # Primary metrics for FarLink Edge represent connection to Master,
        # with Internet bandwidth as fallback or secondary.
        dl_mbps = master_conn["bandwidth_mbps"] if master_conn["bandwidth_mbps"] is not None else internet_conn["download_mbps"]
        ul_mbps = master_conn["bandwidth_mbps"] if master_conn["bandwidth_mbps"] is not None else internet_conn["upload_mbps"]
        lat_ms = master_conn["latency_ms"] if master_conn["latency_ms"] is not None else internet_conn["latency_ms"]
        jit_ms = master_conn["jitter_ms"] if master_conn["jitter_ms"] is not None else internet_conn["jitter_ms"]
        loss_val = master_conn["packet_loss"] if master_conn["packet_loss"] is not None else internet_conn["packet_loss"]

        conn = NetworkDiagnostics.get_connection_type()

        return {
            "id": test_id,
            "test_type": "edge_dual",
            "started_at": started_at,
            "finished_at": finished_at,
            "rtc_time": started_at,
            "duration_seconds": round(time.time() - start_ts, 2),
            "download_mbps": dl_mbps,
            "upload_mbps": ul_mbps,
            "latency_ms": lat_ms,
            "jitter_ms": jit_ms,
            "packet_loss": loss_val,
            "connection_type": conn.get("type", "Ethernet"),
            "interface": conn.get("interface", "eth0"),
            "master_connection": master_conn,
            "internet_connection": internet_conn,
        }

