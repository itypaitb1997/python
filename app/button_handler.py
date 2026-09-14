"""Physical button handler on Raspberry Pi CM5 GPIO with debounce and mock fallback."""
import time
import threading
from typing import Callable, Optional
from app.logger import setup_logger
from app.constants import DEFAULT_PIN_START, DEFAULT_PIN_RESET

logger = setup_logger("button_handler")


class ButtonHandler:
    def __init__(
        self,
        pin_start: int = DEFAULT_PIN_START,
        pin_reset: int = DEFAULT_PIN_RESET,
        on_start_press: Optional[Callable[[], None]] = None,
        on_reset_press: Optional[Callable[[], None]] = None,
    ):
        self.pin_start = pin_start
        self.pin_reset = pin_reset
        self.on_start_press = on_start_press
        self.on_reset_press = on_reset_press
        self.is_hardware_available = False
        self._setup_gpio()

    def _setup_gpio(self) -> None:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            # Active low with internal pull-up
            GPIO.setup(self.pin_start, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.pin_reset, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            GPIO.add_event_detect(
                self.pin_start, GPIO.FALLING, callback=self._handle_start_event, bouncetime=300
            )
            GPIO.add_event_detect(
                self.pin_reset, GPIO.FALLING, callback=self._handle_reset_event, bouncetime=300
            )
            self.is_hardware_available = True
            logger.info(f"Hardware GPIO buttons configured on pins {self.pin_start} (start) & {self.pin_reset} (reset)")
        except Exception as e:
            self.is_hardware_available = False
            logger.info(f"GPIO hardware not available (running in software mock mode): {e}")

    def _handle_start_event(self, channel: int) -> None:
        logger.info("Start button pressed (GPIO event)")
        if self.on_start_press:
            self.on_start_press()

    def _handle_reset_event(self, channel: int) -> None:
        logger.info("Reset button pressed (GPIO event)")
        if self.on_reset_press:
            self.on_reset_press()

    def trigger_mock_start(self) -> None:
        """Helper to simulate start button press in development."""
        self._handle_start_event(self.pin_start)

    def trigger_mock_reset(self) -> None:
        """Helper to simulate reset button press in development."""
        self._handle_reset_event(self.pin_reset)

    def cleanup(self) -> None:
        if self.is_hardware_available:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup([self.pin_start, self.pin_reset])
            except Exception:
                pass
