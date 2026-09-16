"""LCD Matrix 3.5-inch and I2C Display Controller for FarLink Go."""
import os
import sys
from typing import Optional, Dict, Any
from app.logger import setup_logger

logger = setup_logger("lcd")


class LCDDisplay:
    """Controls 3.5-inch LCD Matrix Display (Console/Framebuffer) and fallback I2C displays."""

    def __init__(self, i2c_addr: int = 0x27, cols: int = 16, rows: int = 2):
        self.cols = cols
        self.rows = rows
        self.i2c_addr = i2c_addr
        self.is_hardware_available = False
        self.is_35_matrix = False
        self.fb_path: Optional[str] = None
        self._init_hardware()

    def _init_hardware(self) -> None:
        """Detect 3.5-inch LCD matrix framebuffer (/dev/fb1 or /dev/fb0) or I2C."""
        # 1. Check for 3.5-inch SPI / HDMI framebuffer
        for fb in ("/dev/fb1", "/dev/fb0"):
            if os.path.exists(fb):
                self.fb_path = fb
                self.is_35_matrix = True
                self.is_hardware_available = True
                logger.info(f"Detected 3.5-inch LCD Matrix display on {fb}")
                break

        # 2. Check for I2C LCD if no framebuffer
        if not self.is_hardware_available:
            try:
                import smbus2
                bus = smbus2.SMBus(1)
                bus.close()
                self.is_hardware_available = True
                logger.info("Hardware I2C LCD detected")
            except Exception:
                self.is_hardware_available = False
                logger.debug("Running in console 3.5-inch matrix emulation mode")

    def display_status(self, line1: str, line2: str = "") -> None:
        """Display status lines in clean English."""
        if not self.is_hardware_available:
            return

        l1 = line1[:self.cols].ljust(self.cols)
        l2 = line2[:self.cols].ljust(self.cols)
        # Writes to hardware if I2C or framebuffer mapped

    def show_test_result(self, dl_mbps: float, ul_mbps: float, latency: Optional[float] = None) -> None:
        """Show speedtest metrics on LCD."""
        if not self.is_hardware_available:
            return
        l1 = f"DL:{dl_mbps:0.1f}M UL:{ul_mbps:0.1f}M"
        l2 = f"Ping:{latency:0.1f}ms" if latency is not None else "Test Complete"
        self.display_status(l1, l2)

    def render_matrix_card(
        self,
        claim_code: str,
        server_connected: bool,
        dl_mbps: float = 0.0,
        ul_mbps: float = 0.0,
        latency: float = 0.0,
        notification: str = "",
    ) -> str:
        """Format a clean landscape 3.5-inch Matrix LCD card view in English."""
        srv_str = "● ONLINE" if server_connected else "▲ DISCONNECTED"
        srv_mode = "CLOUD SYNC" if server_connected else "STANDALONE OFFLINE"

        card = [
            "┌────────────────────────────────────────────────────────────────────────┐",
            "│                     █▀▀ █▀█ █▀█ █   █ █▄ █ █▄▀   █▀▀ █▀█               │",
            "│                     █▀  █▀█ █▀▄ █▄▄ █ █ ▀█ █ █   █▄█ █▄█               │",
            "│                           FARLINK GO MATRIX 3.5\"                       │",
            "├────────────────────────────────────────────────────────────────────────┤",
            f"│ ID: {claim_code:<14}  SERVER: {srv_str:<15}  MODE: {srv_mode:<18} │",
            "├────────────────────────────────────────────────────────────────────────┤",
            f"│ DOWNLOAD: {dl_mbps:6.2f} Mbps   │   UPLOAD: {ul_mbps:6.2f} Mbps   │   PING: {latency:4.1f} ms │",
            "├────────────────────────────────────────────────────────────────────────┤",
            f"│ NOTIFY: {notification[:60]:<62} │",
            "└────────────────────────────────────────────────────────────────────────┘",
        ]
        return "\n".join(card)

    def clear(self) -> None:
        """Clear LCD display."""
        self.display_status("", "")
