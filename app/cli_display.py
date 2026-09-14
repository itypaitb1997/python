"""Live Terminal Table Dashboard for FarLink Agent on Raspberry Pi CM5."""
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from app.device_identity import DeviceIdentity
from app.health_monitor import HealthMonitor
from app.database import Database


def _progress_bar(percent: float, width: int = 10) -> str:
    """Create a visual bar for percentage metrics."""
    pct = min(max(percent, 0.0), 100.0)
    filled = int(round(width * pct / 100.0))
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {pct:5.1f}%"


def _format_uptime(seconds: int) -> str:
    """Format seconds into HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}h {m:02d}m {s:02d}s"


def _row_split(left: str, right: str) -> str:
    """Format a 2-column row strictly 80 characters wide."""
    return f"│ {left[:36]:<36} │ {right[:37]:<37} │"


def _row_full(content: str) -> str:
    """Format a full-width row strictly 80 characters wide."""
    return f"│ {content[:76]:<76} │"


class CLIDisplay:
    """Renders formatted real-time tables on the Raspberry Pi terminal."""

    @staticmethod
    def render(
        identity: DeviceIdentity,
        health: HealthMonitor,
        db: Database,
        active_config: Dict[str, Any],
        api_url: str,
        last_test: Optional[Dict[str, Any]] = None,
    ) -> None:
        metrics = health.get_metrics()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Queries from SQLite
        if last_test is None:
            last_test = db.get_latest_test_result()
        total_tests = db.get_test_results_count()
        pending_sync = db.get_pending_sync_count()

        # Hardware values
        cpu_str = _progress_bar(metrics.get("cpu_usage", 0.0), 10)
        ram_str = _progress_bar(metrics.get("ram_usage", 0.0), 10)
        disk_str = _progress_bar(metrics.get("disk_usage", 0.0), 10)
        temp_val = metrics.get("temperature")
        temp_str = f"{temp_val:4.1f} °C" if temp_val is not None else "N/A"
        uptime_str = _format_uptime(metrics.get("uptime", 0))

        # Test results
        if last_test:
            dl_str = f"↓ {last_test.get('download_mbps', 0.0):.2f} Mbps"
            ul_str = f"↑ {last_test.get('upload_mbps', 0.0):.2f} Mbps"
            lat_str = f"{last_test.get('latency_ms', 0.0):.1f} ms"
            jit_str = f"{last_test.get('jitter_ms', 0.0):.1f} ms"
            loss_str = f"{last_test.get('packet_loss', 0.0):.1f} %"
            test_time_str = str(last_test.get("finished_at", "-"))[:19].replace("T", " ")
        else:
            dl_str = "Belum ada pengujian"
            ul_str = "Belum ada pengujian"
            lat_str = "-"
            jit_str = "-"
            loss_str = "-"
            test_time_str = "-"

        reg_status = identity.get_status()
        status_tag = f"{reg_status} (Online)" if reg_status == "ACTIVE" else reg_status

        hb_interval = active_config.get("heartbeat_interval", 60)
        sync_interval = active_config.get("sync_interval", 60)
        config_ver = active_config.get("version", 1)

        border_top = "┌" + "─" * 78 + "┐"
        border_mid = "├" + "─" * 78 + "┤"
        border_split = "├" + "─" * 38 + "┼" + "─" * 39 + "┤"
        border_head = "├" + "─" * 38 + "┬" + "─" * 39 + "┤"
        border_bottom = "└" + "─" * 78 + "┘"

        lines = [
            border_top,
            _row_full(f"{'FARLINK AGENT - RASPBERRY PI CM5 (LIVE MONITOR)':^76}"),
            _row_full(f"{now_str:^76}"),
            border_head,
            _row_split("1. IDENTITAS PERANGKAT", "2. KONEKSI CLOUD & JADWAL"),
            border_split,
            _row_split(f"UUID  : {identity.device_uuid[:26]}", f"Server : {api_url}"),
            _row_split(f"Klaim : {identity.claim_code}", f"Status : {status_tag}"),
            _row_split(f"IP    : {metrics.get('ip_address', '127.0.0.1')}", f"Heartbeat  : Setiap {hb_interval}s"),
            _row_split(f"Versi : Agent v1.0 | Cfg v{config_ver}", f"Sinkronisasi: Setiap {sync_interval}s"),
            border_mid,
            _row_full("3. METRIK HARDWARE & SISTEM (LIVE)"),
            border_head,
            _row_split(f"CPU Usage : {cpu_str}", f"Temperatur : {temp_str}"),
            _row_split(f"RAM Usage : {ram_str}", f"Uptime     : {uptime_str}"),
            _row_split(f"Disk (/)  : {disk_str}", f"OS Ver     : {metrics.get('os_version', 'Linux')}"),
            border_mid,
            _row_full("4. HASIL PENGUKURAN JARINGAN TERAKHIR (LOCAL SQLITE)"),
            border_head,
            _row_split(f"Download  : {dl_str}", f"Latency    : {lat_str}"),
            _row_split(f"Upload    : {ul_str}", f"Jitter     : {jit_str}"),
            _row_split(f"Waktu Tes : {test_time_str}", f"Packet Loss: {loss_str}"),
            border_mid,
            _row_full("5. DATABASE LOKAL & KONTROL FISIK"),
            border_mid,
            _row_full(f"Data Tersimpan di SQLite : {total_tests} hasil pengujian"),
            _row_full(f"Antrean Belum Tersinkron : {pending_sync} item"),
            _row_full("Tombol Fisik CM5         : GPIO 5 (Start Test) | GPIO 6 (Reset/Diag)"),
            border_bottom,
        ]

        table_output = "\n".join(lines)

        # Output to terminal
        if sys.stdout.isatty():
            sys.stdout.write("\033[H\033[2J" + table_output + "\n")
            sys.stdout.flush()
        else:
            print(table_output, flush=True)
