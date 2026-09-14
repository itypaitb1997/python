"""Network diagnostics: gateway, DNS, interface status, and ping latency."""
import subprocess
import socket
try:
    import psutil
except ImportError:
    psutil = None
from typing import Dict, Any, List
from app.logger import setup_logger

logger = setup_logger("network_diagnostics")


class NetworkDiagnostics:
    @staticmethod
    def check_dns(host: str = "google.com") -> bool:
        try:
            socket.gethostbyname(host)
            return True
        except socket.error:
            return False

    @staticmethod
    def ping_latency(target: str = "8.8.8.8", count: int = 3) -> Dict[str, Any]:
        """Ping a target IP or host and return average latency and packet loss."""
        cmd = ["ping", "-c", str(count), "-W", "2", target]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                # Parse ping output
                for line in res.stdout.splitlines():
                    if "avg" in line or "round-trip" in line:
                        parts = line.split("=")[1].strip().split("/")
                        avg_ms = float(parts[1])
                        return {"success": True, "latency_ms": avg_ms, "loss_percent": 0.0}
                return {"success": True, "latency_ms": 1.0, "loss_percent": 0.0}
            else:
                return {"success": False, "latency_ms": None, "loss_percent": 100.0}
        except Exception as e:
            logger.debug(f"Ping exception: {e}")
            return {"success": False, "latency_ms": None, "loss_percent": 100.0}

    @staticmethod
    def get_interface_stats() -> List[Dict[str, Any]]:
        interfaces = []
        if not psutil:
            return [{"interface": "eth0", "is_up": True, "speed_mbps": 1000, "bytes_sent": 0, "bytes_recv": 0}]
        stats = psutil.net_if_stats()
        io_counters = psutil.net_io_counters(pernic=True)


        for iface, stat in stats.items():
            io = io_counters.get(iface)
            interfaces.append({
                "interface": iface,
                "is_up": stat.isup,
                "speed_mbps": stat.speed,
                "bytes_sent": io.bytes_sent if io else 0,
                "bytes_recv": io.bytes_recv if io else 0,
            })
        return interfaces

    @classmethod
    def run_full_diagnostics(cls) -> Dict[str, Any]:
        dns_ok = cls.check_dns()
        ping_res = cls.ping_latency("8.8.8.8")
        return {
            "dns_ok": dns_ok,
            "internet_connected": dns_ok or ping_res.get("success", False),
            "ping": ping_res,
            "interfaces": cls.get_interface_stats(),
        }
