"""Modern Card Dashboard for FarLink Go matching target specification.

Renders modern dark UI cards in terminal and console:
- Header: Blue square logo 'F' + 'FARLINK GO' + Connection Info (Ethernet / Wi-Fi)
- 4 Cards: Download (Mbps), Upload (Mbps), Ping (ms), Jitter (ms)
- Footer: Device code with rack icon + Status badge with checkmark circle
- Strictly uses real test/network data: Displays '-' when not measured or disconnected.
"""
import os
import sys
import re
import shutil
from typing import Dict, Any, Optional
from app.device_identity import DeviceIdentity
from app.health_monitor import HealthMonitor
from app.database import Database, get_rtc_now_str
from app.network_diagnostics import NetworkDiagnostics

# ANSI Color Codes for Modern Dark Theme
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_WHITE = "\033[97m"
C_GRAY = "\033[38;5;245m"
C_DARK = "\033[38;5;240m"
C_BORDER = "\033[38;5;238m"
C_CYAN = "\033[38;5;45m"
C_PURPLE = "\033[38;5;177m"
C_GREEN = "\033[38;5;48m"
C_YELLOW = "\033[38;5;220m"
C_BLUE_BG = "\033[48;5;27;1;97m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _vlen(s: str) -> int:
    """Calculate visible string length excluding ANSI escape sequences."""
    return len(ANSI_RE.sub("", s))


def _fit_cell(content: str, width: int) -> str:
    """Pad content with spaces up to width."""
    v = _vlen(content)
    return content + (" " * max(0, width - v))


class CLIDisplay:
    """Modern card-based dashboard display matching FarLink Go UI."""

    @classmethod
    def render(
        cls,
        identity: DeviceIdentity,
        health: HealthMonitor,
        db: Database,
        active_config: Dict[str, Any],
        api_url: str,
        last_test: Optional[Dict[str, Any]] = None,
        test_running: bool = False,
        server_connected: bool = False,
        notification: Optional[str] = None,
        pending_sync_count: int = 0,
        master_ip: Optional[str] = None,
        master_connected: bool = False,
        master_latency_ms: Optional[float] = None,
        suppress_console: bool = False,
    ) -> None:
        term_cols, term_lines = shutil.get_terminal_size((80, 24))
        m = cls._extract_metrics(health, db, last_test)
        dev_code = identity.claim_code or "FLK-GO-01"

        if test_running:
            status_text = "Running test..."
            status_icon = "●"
            status_col = C_CYAN
        elif last_test:
            status_text = "Test complete"
            status_icon = "✔"
            status_col = C_GREEN
        elif server_connected:
            status_text = "Ready"
            status_icon = "✔"
            status_col = C_GREEN
        else:
            status_text = "Offline"
            status_icon = "●"
            status_col = C_YELLOW

        output = cls.build_dashboard(
            dl_mbps=m["dl_mbps"],
            ul_mbps=m["ul_mbps"],
            latency_ms=m["inet_lat"],
            jitter_ms=m["jitter_val"],
            device_code=dev_code,
            status_text=status_text,
            status_icon=status_icon,
            status_col=status_col,
            term_cols=term_cols,
            notification=notification,
            server_connected=server_connected,
            conn_type=m["conn_type"],
            conn_iface=m["conn_iface"],
            rtc_time=m.get("rtc_time"),
        )
        cls._output_screen(output, suppress_console=suppress_console)

    @classmethod
    def _extract_metrics(cls, health: HealthMonitor, db: Database, last_test: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        metrics = health.get_metrics()
        diag = NetworkDiagnostics.run_full_diagnostics()
        conn = diag.get("connection_type") or NetworkDiagnostics.get_connection_type()

        if last_test is None:
            last_test = db.get_latest_test_result()

        if last_test:
            dl_mbps = last_test.get("download_mbps")
            ul_mbps = last_test.get("upload_mbps")
            inet_lat = last_test.get("latency_ms")
            jitter_val = last_test.get("jitter_ms")
            rtc_val = last_test.get("rtc_time") or last_test.get("finished_at") or get_rtc_now_str()
        else:
            dl_mbps = None
            ul_mbps = None
            inet_lat = diag.get("internet_latency_ms")
            jitter_val = diag.get("jitter_ms")
            rtc_val = get_rtc_now_str()

        return {
            "dl_mbps": dl_mbps,
            "ul_mbps": ul_mbps,
            "inet_lat": inet_lat,
            "jitter_val": jitter_val,
            "rtc_time": rtc_val,
            "conn_type": conn.get("type", "Disconnected"),
            "conn_iface": conn.get("interface", "-"),
            "metrics": metrics,
        }

    @classmethod
    def build_dashboard(
        cls,
        dl_mbps: Optional[float] = None,
        ul_mbps: Optional[float] = None,
        latency_ms: Optional[float] = None,
        jitter_ms: Optional[float] = None,
        device_code: str = "FLK-GO-01",
        status_text: str = "Test complete",
        status_icon: str = "✔",
        status_col: str = C_GREEN,
        term_cols: int = 80,
        notification: Optional[str] = None,
        server_connected: bool = False,
        conn_type: str = "Ethernet",
        conn_iface: str = "eth0",
        rtc_time: Optional[str] = None,
    ) -> str:
        cw = max(24, min(34, (term_cols - 8) // 2))
        horiz = "\u2500" * cw
        top = f"  {C_BORDER}\u256d{horiz}\u256e{C_RESET}  {C_BORDER}\u256d{horiz}\u256e{C_RESET}"
        bot = f"  {C_BORDER}\u2570{horiz}\u256f{C_RESET}  {C_BORDER}\u2570{horiz}\u256f{C_RESET}"

        # Real values or '-' if not measured / disconnected
        dl_str = f"{dl_mbps:.1f}" if (dl_mbps is not None and dl_mbps > 0) else "-"
        ul_str = f"{ul_mbps:.1f}" if (ul_mbps is not None and ul_mbps > 0) else "-"
        ping_str = f"{latency_ms:.0f}" if (latency_ms is not None and latency_ms > 0) else "-"
        jit_str = f"{jitter_ms:.1f}" if (jitter_ms is not None and jitter_ms > 0) else "-"

        # Connection badge
        if conn_type == "Ethernet":
            conn_badge = f"{C_GREEN}[ Ethernet: {conn_iface} ]{C_RESET}"
        elif conn_type == "Wi-Fi":
            conn_badge = f"{C_CYAN}[ Wi-Fi: {conn_iface} ]{C_RESET}"
        else:
            conn_badge = f"{C_YELLOW}[ Disconnected ]{C_RESET}"

        lines = []
        lines.append("")
        # Header: Blue square 'F' + 'FARLINK GO' + Connection type info
        lines.append(f"  {C_BLUE_BG} F {C_RESET}  {C_WHITE}{C_BOLD}FARLINK GO{C_RESET}   {conn_badge}")
        lines.append("")

        # Row 1: Download & Upload Cards
        lines.append(top)
        c1_head = f"  {C_CYAN}\u2193{C_RESET} {C_GRAY}Download{C_RESET}"
        c2_head = f"  {C_PURPLE}\u2191{C_RESET} {C_GRAY}Upload{C_RESET}"
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{_fit_cell(c1_head, cw)}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{_fit_cell(c2_head, cw)}{C_BORDER}\u2502{C_RESET}")
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{' '*cw}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{' '*cw}{C_BORDER}\u2502{C_RESET}")

        c1_val = f"  {C_WHITE}{C_BOLD}{dl_str}{C_RESET}"
        c2_val = f"  {C_WHITE}{C_BOLD}{ul_str}{C_RESET}"
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{_fit_cell(c1_val, cw)}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{_fit_cell(c2_val, cw)}{C_BORDER}\u2502{C_RESET}")
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{' '*cw}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{' '*cw}{C_BORDER}\u2502{C_RESET}")

        c1_unit = f"  {C_DARK}Mbps{C_RESET}"
        c2_unit = f"  {C_DARK}Mbps{C_RESET}"
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{_fit_cell(c1_unit, cw)}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{_fit_cell(c2_unit, cw)}{C_BORDER}\u2502{C_RESET}")
        lines.append(bot)
        lines.append("")

        # Row 2: Ping & Jitter Cards
        lines.append(top)
        p_sp = " " * max(1, cw - len(ping_str) - 11)
        j_sp = " " * max(1, cw - len(jit_str) - 13)
        c3_row = f"  {C_GRAY}Ping{C_RESET}{p_sp}{C_WHITE}{C_BOLD}{ping_str}{C_RESET} {C_GRAY}ms{C_RESET}  "
        c4_row = f"  {C_GRAY}Jitter{C_RESET}{j_sp}{C_WHITE}{C_BOLD}{jit_str}{C_RESET} {C_GRAY}ms{C_RESET}  "
        lines.append(f"  {C_BORDER}\u2502{C_RESET}{_fit_cell(c3_row, cw)}{C_BORDER}\u2502{C_RESET}  {C_BORDER}\u2502{C_RESET}{_fit_cell(c4_row, cw)}{C_BORDER}\u2502{C_RESET}")
        lines.append(bot)
        lines.append("")

        # Footer: Server Rack Icon + Device Code (Left), RTC Time, Status Badge (Right)
        clean_rtc = ""
        if rtc_time:
            try:
                t_part = rtc_time.replace("T", " ").split(".")[0].split("+")[0].strip()
                if " " in t_part:
                    t_part = t_part.split(" ")[1]
                clean_rtc = f"  {C_DARK}[RTC {t_part}]{C_RESET}"
            except Exception:
                pass

        f_left = f"  {C_GRAY}\u268c {device_code}{C_RESET}{clean_rtc}"
        f_right = f"{status_col}{status_icon} {status_text}{C_RESET}"

        total_w = cw * 2 + 6
        space_len = max(4, total_w - _vlen(f_left) - _vlen(f_right))
        lines.append(f"{f_left}{' ' * space_len}{f_right}")

        # Notification or action message
        if notification:
            notif_clean = notification[:total_w - 4]
            lines.append(f"  {C_DARK}{notif_clean}{C_RESET}")
        else:
            lines.append(f"  {C_DARK}[START / GPIO 5] Speedtest  │  [RESET / GPIO 6] Re-probe{C_RESET}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _output_screen(text: str, suppress_console: bool = False) -> None:
        # When graphical framebuffer GUI is active on physical screen, do not overwrite it with text console
        if suppress_console:
            if sys.stdout.isatty():
                try:
                    sys.stdout.write("\033[H\033[2J" + text + "\n")
                    sys.stdout.flush()
                except Exception:
                    pass
            return

        try:
            sys.stdout.write("\033[H\033[2J" + text + "\n")
            sys.stdout.flush()
        except Exception:
            print(text, flush=True)

        # Fallback to /dev/tty1 only in headless mode when no graphical framebuffer exists
        if os.path.exists("/dev/tty1") and not sys.stdout.isatty():
            try:
                with open("/dev/tty1", "w", encoding="utf-8") as f:
                    f.write("\033[H\033[2J" + text + "\n")
            except Exception:
                pass
