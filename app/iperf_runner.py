"""iPerf3 runner for network throughput, jitter, and loss measurements."""
import subprocess
import json
import shutil
from typing import Dict, Any, Optional
from app.logger import setup_logger

logger = setup_logger("iperf_runner")


class IperfRunner:
    def __init__(self):
        self.iperf_bin = shutil.which("iperf3")

    def run_client(
        self,
        server_ip: str,
        port: int = 5201,
        duration: int = 10,
        streams: int = 1,
        udp: bool = False,
        bandwidth_limit: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute iPerf3 client test and return parsed json metrics."""
        if not self.iperf_bin:
            logger.warning("iperf3 binary not found on system. Simulating result.")
            return {
                "error": "iperf3_not_installed",
                "bandwidth_mbps": 0.0,
                "jitter_ms": 0.0,
                "packet_loss": 0.0,
            }

        cmd = [
            self.iperf_bin,
            "-c", server_ip,
            "-p", str(port),
            "-t", str(duration),
            "-P", str(streams),
            "-J",  # Output JSON
        ]

        if udp:
            cmd.append("-u")
            if bandwidth_limit:
                cmd.extend(["-b", bandwidth_limit])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 15)
            if res.returncode != 0:
                logger.error(f"iperf3 failed with code {res.returncode}: {res.stderr}")
                return {"error": res.stderr.strip() or "iperf3_execution_failed"}

            data = json.loads(res.stdout)
            end = data.get("end", {})
            sum_sent = end.get("sum_sent", {})
            sum_received = end.get("sum_received", {})

            # Bits per second converted to Mbps
            bps = sum_received.get("bits_per_second") or sum_sent.get("bits_per_second", 0)
            bandwidth_mbps = round(bps / 1_000_000, 2)

            jitter_ms = None
            packet_loss = None
            if udp:
                sum_obj = end.get("sum", {})
                jitter_ms = round(sum_obj.get("jitter_ms", 0.0), 2)
                packet_loss = round(sum_obj.get("lost_percent", 0.0), 2)

            return {
                "bandwidth_mbps": bandwidth_mbps,
                "jitter_ms": jitter_ms,
                "packet_loss": packet_loss,
                "raw_result": data,
            }
        except subprocess.TimeoutExpired:
            logger.error("iperf3 test timed out")
            return {"error": "timeout"}
        except Exception as e:
            logger.error(f"Exception during iperf3 run: {e}")
            return {"error": str(e)}

    def start_server_process(self, port: int = 5201) -> Optional[subprocess.Popen]:
        """Start background iPerf3 server process for Slave mode."""
        if not self.iperf_bin:
            logger.warning("iperf3 binary not found. Cannot start server.")
            return None
        cmd = [self.iperf_bin, "-s", "-p", str(port)]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
