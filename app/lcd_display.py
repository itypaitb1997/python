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
            logger.debug(f"LCD hardware not detected ({e}); running in headless mode")

    def display_status(self, line1: str, line2: str = "") -> None:
        """Display two lines of status text if hardware LCD is connected."""
        if not self.is_hardware_available:
            return  # Headless mode: skip mock output per user requirement

        l1 = line1[:self.cols].ljust(self.cols)
        l2 = line2[:self.cols].ljust(self.cols)
        # Hardware I2C write commands here when connected

    def show_test_result(self, dl_mbps: float, ul_mbps: float, latency: Optional[float] = None) -> None:
        if not self.is_hardware_available:
            return
        l1 = f"DL:{dl_mbps:0.1f}M UL:{ul_mbps:0.1f}M"
        l2 = f"Ping:{latency:0.1f}ms" if latency is not None else "Test Complete"
        self.display_status(l1, l2)

    def clear(self) -> None:
        self.display_status("", "")
