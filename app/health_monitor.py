"""System Health and Hardware Monitor."""
import os
import platform
import time
try:
    import psutil
except ImportError:
    psutil = None
from typing import Dict, Any, Optional


class HealthMonitor:
    def __init__(self):
        self._boot_time = psutil.boot_time() if psutil else time.time()

    def get_cpu_usage(self) -> float:
        return float(psutil.cpu_percent(interval=None)) if psutil else 0.0

    def get_ram_usage(self) -> float:
        return float(psutil.virtual_memory().percent) if psutil else 0.0

    def get_disk_usage(self) -> float:
        if psutil:
            return float(psutil.disk_usage("/").percent)
        try:
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            return round(((total - free) / total) * 100.0, 1)
        except Exception:
            return 0.0


    def get_temperature(self) -> Optional[float]:
        """Read SoC temperature on Linux / Raspberry Pi."""
        try:
            # Raspberry Pi thermal zone
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    temp_raw = f.read().strip()
                    return round(float(temp_raw) / 1000.0, 1)
            # Generic psutil sensors (if supported on OS)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            return round(entries[0].current, 1)
        except Exception:
            pass
        return None

    def get_uptime_seconds(self) -> int:
        return int(time.time() - self._boot_time)

    def get_ip_address(self) -> str:
        """Get local primary IP address."""
        if psutil:
            for iface, addrs in psutil.net_if_addrs().items():
                if not iface.startswith("lo"):
                    for addr in addrs:
                        if addr.family.name == "AF_INET" and not addr.address.startswith("127."):
                            return addr.address
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.5)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"



    def get_metrics(self) -> Dict[str, Any]:
        return {
            "cpu_usage": self.get_cpu_usage(),
            "ram_usage": self.get_ram_usage(),
            "disk_usage": self.get_disk_usage(),
            "temperature": self.get_temperature(),
            "uptime": self.get_uptime_seconds(),
            "ip_address": self.get_ip_address(),
            "os_version": f"{platform.system()} {platform.release()}",
        }
