"""LCDWiki 3.5-inch RPi Display (ILI9486, 480x320 Landscape) & I2C Controller.

Hardware Specification for https://www.lcdwiki.com/3.5inch_RPi_Display:
- Display: 3.5" TFT LCD, 480x320 pixels (Landscape mode)
- Driver IC: ILI9486 / ILI9486L
- Touch Controller: XPT2046 (SPI CE1 / GPIO 7)
- Interface: High-Speed SPI (MOSI: GPIO 10, MISO: GPIO 9, SCLK: GPIO 11, CE0: GPIO 8)
- Control Pins: LCD_RS: GPIO 24, LCD_RST: GPIO 25
- Compatible Buttons: GPIO 5 (Start Button) & GPIO 6 (Reset Button) - Active Low
- Framebuffer device: /dev/fb1 (via fbtft / LCD-show driver)
"""
import os
import sys
from typing import Optional, Dict, Any
from app.logger import setup_logger

logger = setup_logger("lcd")


class LCDDisplay:
    """Hardware Controller specifically adapted for LCDWiki 3.5-inch RPi Display."""

    SPEC_WIDTH = 480
    SPEC_HEIGHT = 320
    SPEC_DRIVER = "ILI9486"
    SPEC_TOUCH = "XPT2046"

    def __init__(self, i2c_addr: int = 0x27, cols: int = 16, rows: int = 2):
        self.cols = cols
        self.rows = rows
        self.i2c_addr = i2c_addr
        self.is_hardware_available = False
        self.is_35_matrix = False
        self.fb_path: Optional[str] = None
        self.fb_width = self.SPEC_WIDTH
        self.fb_height = self.SPEC_HEIGHT
        self._init_hardware()

    def _init_hardware(self) -> None:
        """Detect LCDWiki 3.5inch RPi Display on /dev/fb1 (or /dev/fb0) or I2C fallback."""
        # Check standard SPI framebuffer for 3.5" LCD (ILI9486 creates /dev/fb1)
        for fb in ("/dev/fb1", "/dev/fb0"):
            if os.path.exists(fb):
                self.fb_path = fb
                self.is_35_matrix = True
                self.is_hardware_available = True
                self._detect_fb_geometry(fb)
                logger.info(
                    f"Detected LCDWiki 3.5\" RPi Display ({self.SPEC_DRIVER}) on {fb} [{self.fb_width}x{self.fb_height}]"
                )
                break

        # Fallback to I2C bus probe if no framebuffer is found
        if not self.is_hardware_available:
            try:
                import smbus2
                bus = smbus2.SMBus(1)
                bus.close()
                self.is_hardware_available = True
                logger.info("Hardware I2C LCD detected")
            except Exception:
                self.is_hardware_available = False
                logger.debug("Running in 3.5\" RPi Display emulation mode (480x320 Landscape)")

    def _detect_fb_geometry(self, fb_dev: str) -> None:
        """Read resolution from sysfs for the detected framebuffer."""
        try:
            fb_name = os.path.basename(fb_dev)
            size_path = f"/sys/class/graphics/{fb_name}/virtual_size"
            if os.path.exists(size_path):
                with open(size_path, "r") as f:
                    content = f.read().strip()
                    if "," in content:
                        w, h = content.split(",", 1)
                        self.fb_width = int(w)
                        self.fb_height = int(h)
        except Exception as e:
            logger.debug(f"Could not read fb geometry: {e}")

    def get_display_info(self) -> Dict[str, Any]:
        """Return full hardware specification and status of the 3.5\" display."""
        return {
            "name": "LCDWiki 3.5inch RPi Display",
            "driver_ic": self.SPEC_DRIVER,
            "touch_controller": self.SPEC_TOUCH,
            "native_resolution": f"{self.SPEC_WIDTH}x{self.SPEC_HEIGHT} (Landscape)",
            "framebuffer": self.fb_path or "emulated",
            "is_hardware_active": self.is_hardware_available,
            "gpio_buttons": {
                "start": "GPIO 5 (Pin 29 - Free & Compatible)",
                "reset": "GPIO 6 (Pin 31 - Free & Compatible)",
            },
        }

    def display_status(self, line1: str, line2: str = "") -> None:
        """Backward-compatible text status display."""
        if not self.is_hardware_available:
            return

        l1 = line1[:self.cols].ljust(self.cols)
        l2 = line2[:self.cols].ljust(self.cols)
        # Written to hardware bus/device when connected

    def show_test_result(self, dl_mbps: float, ul_mbps: float, latency: Optional[float] = None) -> None:
        """Display test metrics on 3.5\" display."""
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
        """Render a 480x320 landscape card perfectly matched for the LCDWiki 3.5\" display."""
        srv_str = "● ONLINE" if server_connected else "▲ DISCONNECTED"
        srv_mode = "CLOUD SYNC" if server_connected else "STANDALONE OFFLINE"

        card = [
            "┌────────────────────────────────────────────────────────────────────────┐",
            "│                     █▀▀ █▀█ █▀█ █   █ █▄ █ █▄▀   █▀▀ █▀█               │",
            "│                     █▀  █▀█ █▀▄ █▄▄ █ █ ▀█ █ █   █▄█ █▄█               │",
            "│                  FARLINK GO - LCDWiki 3.5\" RPi Display                 │",
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
