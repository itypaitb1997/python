"""LCD Controller for Raspberry Pi 5 Lite (ILI9486/ST7789 Framebuffer /dev/fb0, /dev/fb1 & HDMI).

Renders modern dark UI dashboard matching FarLink Go display specifications:
- Dimensions: 480x320 landscape (or scales to screen resolution)
- Header: Blue square logo 'F' + 'FARLINK GO'
- 4 Cards: Download (Mbps), Upload (Mbps), Ping (ms), Jitter (ms)
- Footer: Device code with rack icon + Status badge with checkmark circle
"""
import os
import sys
from typing import Optional, Dict, Any, Tuple
from app.logger import setup_logger

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

logger = setup_logger("lcd")


class LCDDisplay:
    """Graphical Framebuffer & LCD Controller for Raspberry Pi 5 Lite."""

    SPEC_WIDTH = 480
    SPEC_HEIGHT = 320
    SPEC_DRIVER = "ILI9486 / DRM Framebuffer"

    def __init__(self, i2c_addr: int = 0x27, cols: int = 16, rows: int = 2):
        self.cols = cols
        self.rows = rows
        self.i2c_addr = i2c_addr
        self.is_hardware_available = False
        self.fb_path: Optional[str] = None
        self.fb_width = self.SPEC_WIDTH
        self.fb_height = self.SPEC_HEIGHT
        self.fb_bpp = 16

        # Cached display state
        self.last_dl: float = 0.0
        self.last_ul: float = 0.0
        self.last_ping: float = 0.0
        self.last_jitter: float = 0.0
        self.device_code: str = "FLK-GO-01"
        self.status_text: str = "Ready"
        self.status_color: str = "#22c55e"

        self._init_hardware()
        # Draw initial screen
        self.update_dashboard(
            dl_mbps=0.0,
            ul_mbps=0.0,
            latency_ms=0.0,
            jitter_ms=0.0,
            device_code=self.device_code,
            status_text="Ready",
            status_color="#22c55e",
        )

    def _init_hardware(self) -> None:
        """Detect Linux framebuffer (/dev/fb1 or /dev/fb0) on Raspberry Pi."""
        for fb in ("/dev/fb1", "/dev/fb0"):
            if os.path.exists(fb):
                self.fb_path = fb
                self.is_hardware_available = True
                self._detect_fb_geometry(fb)
                logger.info(
                    f"Detected Framebuffer Display on {fb} [{self.fb_width}x{self.fb_height}, {self.fb_bpp} bpp]"
                )
                break

        if not self.is_hardware_available:
            logger.info("Running in headless display mode. UI rendered to /tmp/farlink_display.png.")

    def _detect_fb_geometry(self, fb_dev: str) -> None:
        """Read resolution and bpp from sysfs for the detected framebuffer."""
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

            bpp_path = f"/sys/class/graphics/{fb_name}/bits_per_pixel"
            if os.path.exists(bpp_path):
                with open(bpp_path, "r") as f:
                    self.fb_bpp = int(f.read().strip())
        except Exception as e:
            logger.debug(f"Could not read fb geometry: {e}")

    def _get_font(self, size: int, bold: bool = False):
        """Retrieve system font or fallback to Pillow's scalable default font."""
        if not PILLOW_AVAILABLE:
            return None
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFCompact.ttf",
        ]
        for c in candidates:
            if os.path.exists(c):
                try:
                    return ImageFont.truetype(c, size)
                except Exception:
                    pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def render_dashboard_image(
        self,
        dl_mbps: float,
        ul_mbps: float,
        latency_ms: float,
        jitter_ms: float,
        device_code: str = "FLK-GO-01",
        status_text: str = "Test complete",
        status_color: str = "#22c55e",
    ) -> Any:
        """Render modern graphical FarLink dashboard matching target specifications."""
        if not PILLOW_AVAILABLE:
            return None

        W, H = self.SPEC_WIDTH, self.SPEC_HEIGHT
        img = Image.new("RGB", (W, H), color="#090a0d")
        draw = ImageDraw.Draw(img)

        f_header = self._get_font(18, bold=True)
        f_logo = self._get_font(17, bold=True)
        f_label = self._get_font(15, bold=False)
        f_metric = self._get_font(54, bold=True)
        f_unit = self._get_font(14, bold=False)
        f_small_val = self._get_font(24, bold=True)
        f_footer = self._get_font(14, bold=False)

        # 1. Header: Blue icon 'F' and Title 'FARLINK GO'
        draw.rounded_rectangle([(14, 14), (44, 44)], radius=8, fill="#2b72ee")
        draw.text((23, 19), "F", fill="#ffffff", font=f_logo)
        draw.text((58, 20), "FARLINK GO", fill="#ffffff", font=f_header)

        # Helper vector drawer functions
        def draw_down_arrow(x: int, y: int, color: str = "#38bdf8"):
            draw.line([(x + 4, y), (x + 4, y + 11)], fill=color, width=2)
            draw.polygon([(x + 1, y + 8), (x + 7, y + 8), (x + 4, y + 13)], fill=color)

        def draw_up_arrow(x: int, y: int, color: str = "#c084fc"):
            draw.line([(x + 4, y + 3), (x + 4, y + 13)], fill=color, width=2)
            draw.polygon([(x + 1, y + 5), (x + 7, y + 5), (x + 4, y)], fill=color)

        def draw_rack_icon(x: int, y: int, color: str = "#64748b"):
            draw.rounded_rectangle([(x, y), (x + 15, y + 6)], radius=2, outline=color, width=1)
            draw.ellipse([(x + 11, y + 2), (x + 13, y + 4)], fill=color)
            draw.rounded_rectangle([(x, y + 8), (x + 15, y + 14)], radius=2, outline=color, width=1)
            draw.ellipse([(x + 11, y + 10), (x + 13, y + 12)], fill=color)

        def draw_status_badge(x: int, y: int, color: str = "#22c55e", text: str = "Test complete"):
            draw.ellipse([(x, y), (x + 14, y + 14)], outline=color, width=2)
            draw.line([(x + 3, y + 7), (x + 6, y + 10)], fill=color, width=2)
            draw.line([(x + 6, y + 10), (x + 11, y + 4)], fill=color, width=2)
            draw.text((x + 20, y - 2), text, fill=color, font=f_footer)

        # 2. Card 1: Download
        dl_str = f"{dl_mbps:.0f}" if dl_mbps >= 10 else f"{dl_mbps:.1f}"
        c1 = [(12, 54), (234, 194)]
        draw.rounded_rectangle(c1, radius=16, fill="#15161c", outline="#1f222b", width=1)
        draw_down_arrow(26, 70, "#38bdf8")
        draw.text((42, 67), "Download", fill="#94a3b8", font=f_label)
        draw.text((26, 94), dl_str, fill="#ffffff", font=f_metric)
        draw.text((26, 156), "Mbps", fill="#64748b", font=f_unit)

        # 3. Card 2: Upload
        ul_str = f"{ul_mbps:.0f}" if ul_mbps >= 10 else f"{ul_mbps:.1f}"
        c2 = [(246, 54), (468, 194)]
        draw.rounded_rectangle(c2, radius=16, fill="#15161c", outline="#1f222b", width=1)
        draw_up_arrow(260, 70, "#c084fc")
        draw.text((276, 67), "Upload", fill="#94a3b8", font=f_label)
        draw.text((260, 94), ul_str, fill="#ffffff", font=f_metric)
        draw.text((260, 156), "Mbps", fill="#64748b", font=f_unit)

        # 4. Card 3: Ping
        ping_str = f"{latency_ms:.0f}" if latency_ms >= 10 else f"{latency_ms:.1f}"
        c3 = [(12, 204), (234, 266)]
        draw.rounded_rectangle(c3, radius=16, fill="#15161c", outline="#1f222b", width=1)
        draw.text((26, 224), "Ping", fill="#94a3b8", font=f_label)
        draw.text((160, 219), ping_str, fill="#ffffff", font=f_small_val)
        draw.text((196, 224), "ms", fill="#94a3b8", font=f_unit)

        # 5. Card 4: Jitter
        jitter_str = f"{jitter_ms:.1f}"
        c4 = [(246, 204), (468, 266)]
        draw.rounded_rectangle(c4, radius=16, fill="#15161c", outline="#1f222b", width=1)
        draw.text((260, 224), "Jitter", fill="#94a3b8", font=f_label)
        draw.text((388, 219), jitter_str, fill="#ffffff", font=f_small_val)
        draw.text((428, 224), "ms", fill="#94a3b8", font=f_unit)

        # 6. Footer: Rack Icon + Device Code (Left), Status Badge (Right)
        draw_rack_icon(14, 282, "#64748b")
        draw.text((36, 280), device_code, fill="#64748b", font=f_footer)
        draw_status_badge(336, 282, status_color, status_text)

        return img

    def render_to_framebuffer(self, image: Any) -> None:
        """Write PIL Image directly to Raspberry Pi framebuffer (/dev/fb0 or /dev/fb1)."""
        if not PILLOW_AVAILABLE or image is None:
            return

        # Always save copy for preview & verification
        try:
            image.save("/tmp/farlink_display.png")
        except Exception:
            pass

        if not self.fb_path or not os.path.exists(self.fb_path):
            return

        try:
            # Resize image to match framebuffer resolution if needed
            if image.size != (self.fb_width, self.fb_height):
                target_img = image.resize((self.fb_width, self.fb_height))
            else:
                target_img = image

            # Convert to raw byte format based on bits per pixel
            if self.fb_bpp == 16:
                # RGB565 format for 16-bit SPI LCDs
                rgb = target_img.convert("RGB")
                pixels = list(rgb.getdata())
                raw_bytes = bytearray(len(pixels) * 2)
                idx = 0
                for r, g, b in pixels:
                    val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                    raw_bytes[idx] = val & 0xFF
                    raw_bytes[idx + 1] = (val >> 8) & 0xFF
                    idx += 2
            else:
                # 32-bit format (BGRA / XRGB) for standard HDMI / DRM display
                bgra = target_img.convert("RGBA")
                raw_bytes = bytearray()
                for r, g, b, a in bgra.getdata():
                    raw_bytes.append(b)
                    raw_bytes.append(g)
                    raw_bytes.append(r)
                    raw_bytes.append(a)

            with open(self.fb_path, "wb") as f:
                f.write(raw_bytes)
        except Exception as e:
            logger.debug(f"Writing to framebuffer failed: {e}")

    def update_dashboard(
        self,
        dl_mbps: float = 0.0,
        ul_mbps: float = 0.0,
        latency_ms: float = 0.0,
        jitter_ms: float = 0.0,
        device_code: Optional[str] = None,
        status_text: Optional[str] = None,
        status_color: Optional[str] = None,
    ) -> None:
        """Update and redraw FarLink graphical dashboard."""
        self.last_dl = dl_mbps
        self.last_ul = ul_mbps
        self.last_ping = latency_ms
        self.last_jitter = jitter_ms
        if device_code:
            self.device_code = device_code
        if status_text:
            self.status_text = status_text
        if status_color:
            self.status_color = status_color

        img = self.render_dashboard_image(
            dl_mbps=self.last_dl,
            ul_mbps=self.last_ul,
            latency_ms=self.last_ping,
            jitter_ms=self.last_jitter,
            device_code=self.device_code,
            status_text=self.status_text,
            status_color=self.status_color,
        )
        self.render_to_framebuffer(img)

    def show_test_result(
        self,
        dl_mbps: float,
        ul_mbps: float,
        latency: Optional[float] = None,
        jitter: Optional[float] = None,
        device_code: Optional[str] = None,
        status_text: str = "Test complete",
    ) -> None:
        """Display test metrics on dashboard screen."""
        self.update_dashboard(
            dl_mbps=dl_mbps,
            ul_mbps=ul_mbps,
            latency_ms=latency if latency is not None else 0.0,
            jitter_ms=jitter if jitter is not None else 1.5,
            device_code=device_code or self.device_code,
            status_text=status_text,
            status_color="#22c55e",
        )

    def display_status(self, line1: str, line2: str = "") -> None:
        """Update status line while retaining metrics."""
        msg = f"{line1} {line2}".strip()
        color = "#22c55e" if "OK" in msg or "Online" in msg or "complete" in msg.lower() else "#38bdf8"
        self.update_dashboard(
            dl_mbps=self.last_dl,
            ul_mbps=self.last_ul,
            latency_ms=self.last_ping,
            jitter_ms=self.last_jitter,
            status_text=line1[:20],
            status_color=color,
        )

    def clear(self) -> None:
        """Clear display."""
        if PILLOW_AVAILABLE:
            blank = Image.new("RGB", (self.SPEC_WIDTH, self.SPEC_HEIGHT), color="#000000")
            self.render_to_framebuffer(blank)

    def render_matrix_card(
        self,
        claim_code: str,
        server_connected: bool,
        dl_mbps: float = 0.0,
        ul_mbps: float = 0.0,
        latency: float = 0.0,
        notification: str = "",
    ) -> str:
        """Render a 480x320 landscape ASCII card for CLI / log / testing."""
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
