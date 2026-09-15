"""System Health and Hardware Monitor."""
import os
import platform
import time
from typing import Dict, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None


class HealthMonitor:
    def __init__(self):
        self._boot_time = self._get_initial_boot_time()
        self._prev_cpu_idle: Optional[float] = None
        self._prev_cpu_total: Optional[float] = None

    def _get_initial_boot_time(self) -> float:
        # Check /proc/uptime first (Linux standard)
        try:
            if os.path.exists("/proc/uptime"):
                with open("/proc/uptime", "r") as f:
                    up_sec = float(f.readline().split()[0])
                    return time.time() - up_sec
        except Exception:
            pass

        if psutil:
            try:
                return psutil.boot_time()
            except Exception:
                pass

        return time.time()

    def get_cpu_usage(self) -> float:
        # 1. Direct Linux /proc/stat
        try:
            if os.path.exists("/proc/stat"):
                with open("/proc/stat", "r") as f:
                    first_line = f.readline()
                if first_line.startswith("cpu "):
                    parts = [float(x) for x in first_line.split()[1:]]
                    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
                    total = sum(parts)
                    if self._prev_cpu_idle is not None and self._prev_cpu_total is not None:
                        idle_delta = idle - self._prev_cpu_idle
                        total_delta = total - self._prev_cpu_total
                        self._prev_cpu_idle = idle
                        self._prev_cpu_total = total
                        if total_delta > 0:
                            usage = round((1.0 - (idle_delta / total_delta)) * 100.0, 1)
                            return max(0.0, min(100.0, usage))
                    else:
                        self._prev_cpu_idle = idle
                        self._prev_cpu_total = total
        except Exception:
            pass

        # 2. psutil with fallback
        if psutil:
            try:
                val = float(psutil.cpu_percent(interval=None))
                if val > 0.0:
                    return val
                return float(psutil.cpu_percent(interval=0.1))
            except Exception:
                pass

        # 3. Load average fallback
        try:
            load1, _, _ = os.getloadavg()
            cpu_count = os.cpu_count() or 4
            return round(min(100.0, (load1 / cpu_count) * 100.0), 1)
        except Exception:
            pass

        return 0.0

    def get_ram_usage(self) -> float:
        # 1. Direct Linux /proc/meminfo (works on all Linux / Raspberry Pi OS)
        try:
            if os.path.exists("/proc/meminfo"):
                meminfo = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            meminfo[parts[0].strip()] = parts[1].strip().split()[0]
                total = float(meminfo.get("MemTotal", 0))
                if total > 0:
                    if "MemAvailable" in meminfo:
                        avail = float(meminfo["MemAvailable"])
                        return round(((total - avail) / total) * 100.0, 1)
                    elif "MemFree" in meminfo:
                        free = float(meminfo["MemFree"])
                        buffers = float(meminfo.get("Buffers", 0))
                        cached = float(meminfo.get("Cached", 0))
                        avail = free + buffers + cached
                        return round(((total - avail) / total) * 100.0, 1)
        except Exception:
            pass

        # 2. psutil
        if psutil:
            try:
                return float(psutil.virtual_memory().percent)
            except Exception:
                pass

        return 0.0

    def get_disk_usage(self) -> float:
        # 1. os.statvfs (POSIX standard)
        try:
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            if total > 0:
                return round(((total - free) / total) * 100.0, 1)
        except Exception:
            pass

        if psutil:
            try:
                return float(psutil.disk_usage("/").percent)
            except Exception:
                pass

        return 0.0

    def get_temperature(self) -> Optional[float]:
        """Read SoC temperature on Linux / Raspberry Pi."""
        try:
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    temp_raw = f.read().strip()
                    return round(float(temp_raw) / 1000.0, 1)

            if psutil and hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            return round(entries[0].current, 1)
        except Exception:
            pass
        return None

    def get_uptime_seconds(self) -> int:
        # 1. Read /proc/uptime (standard Linux)
        try:
            if os.path.exists("/proc/uptime"):
                with open("/proc/uptime", "r") as f:
                    return int(float(f.readline().split()[0]))
        except Exception:
            pass

        # 2. Boot time delta
        return max(1, int(time.time() - self._boot_time))

    def get_ip_address(self) -> str:
        """Get local primary IP address."""
        if psutil:
            try:
                for iface, addrs in psutil.net_if_addrs().items():
                    if not iface.startswith("lo"):
                        for addr in addrs:
                            if addr.family.name == "AF_INET" and not addr.address.startswith("127."):
                                return addr.address
            except Exception:
                pass

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
