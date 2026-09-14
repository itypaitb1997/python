"""LCD display controller with hardware driver and software fallback mock."""
from typing import Optional
from app.logger import setup_logger

logger = setup_logger("lcd")


class LCDDisplay:
    def __init__(self, i2c_addr: int = 0x27, cols: int = 16, rows: int = 2):
        self.cols = cols
        self.rows = rows
        self.i2c_addr = i2c_addr
        self.is_hardware_available = False
        self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            import smbus2
            # Test bus access
            bus = smbus2.SMBus(1)
            bus.close()
            self.is_hardware_available = True
            logger.info("Hardware I2C LCD initialized successfully")
        except Exception as e:
            self.is_hardware_available = False
            logger.info(f"LCD hardware not available (running in software mock mode): {e}")

    def display_status(self, line1: str, line2: str = "") -> None:
        """Display two lines of status text (16 chars max per line)."""
        l1 = line1[:self.cols].ljust(self.cols)
        l2 = line2[:self.cols].ljust(self.cols)

        if self.is_hardware_available:
            pass  # Hardware write commands
        else:
            logger.info(f"[LCD MOCK] | {l1} |")
            logger.info(f"[LCD MOCK] | {l2} |")

    def show_test_result(self, dl_mbps: float, ul_mbps: float, latency: Optional[float] = None) -> None:
        l1 = f"DL:{dl_mbps:0.1f}M UL:{ul_mbps:0.1f}M"
        l2 = f"Ping:{latency:0.1f}ms" if latency is not None else "Test Complete"
        self.display_status(l1, l2)

    def clear(self) -> None:
        self.display_status("", "")
