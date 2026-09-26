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
        self.active_backend: str = "mock"
        self._gpiozero_btns = []
        self._setup_gpio()

    def _setup_gpio(self) -> None:
        # Tier 1: gpiozero (official recommendation for Raspberry Pi CM5 / Pi 5 with RP1 chip & Bookworm OS)
        try:
            from gpiozero import Button
            btn_start = Button(self.pin_start, pull_up=True, bounce_time=0.15)
            btn_reset = Button(self.pin_reset, pull_up=True, bounce_time=0.15)

            btn_start.when_pressed = self._handle_start_event
            btn_reset.when_pressed = self._handle_reset_event

            self._gpiozero_btns = [btn_start, btn_reset]
            self.is_hardware_available = True
            self.active_backend = "gpiozero"
            logger.info(f"Hardware GPIO buttons configured on pins {self.pin_start} (start) & {self.pin_reset} (reset) using gpiozero (CM5 RP1 active-low)")
            return
        except Exception as e_gz:
            logger.debug(f"gpiozero backend not available: {e_gz}")

        # Tier 2: RPi.GPIO (BCM legacy for Pi 3/4)
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
            self.active_backend = "RPi.GPIO"
            logger.info(f"Hardware GPIO buttons configured on pins {self.pin_start} (start) & {self.pin_reset} (reset) using RPi.GPIO (active-low)")
            return
        except Exception as e_rpi:
            logger.debug(f"RPi.GPIO backend not available: {e_rpi}")

        # Tier 3: Software mock fallback
        self.is_hardware_available = False
        self.active_backend = "mock"
        logger.info(f"GPIO hardware not available on current environment. Buttons {self.pin_start} & {self.pin_reset} ready in software mock mode.")

    def _handle_start_event(self, *args) -> None:
        logger.info(f"Start button pressed (GPIO {self.pin_start} event)")
        if self.on_start_press:
            self.on_start_press()

    def _handle_reset_event(self, *args) -> None:
        logger.info(f"Reset button pressed (GPIO {self.pin_reset} event)")
        if self.on_reset_press:
            self.on_reset_press()

    def trigger_mock_start(self) -> None:
        """Helper to simulate start button press in development."""
        self._handle_start_event(self.pin_start)

    def trigger_mock_reset(self) -> None:
        """Helper to simulate reset button press in development."""
        self._handle_reset_event(self.pin_reset)

    def cleanup(self) -> None:
        if self.active_backend == "gpiozero":
            for b in self._gpiozero_btns:
                try:
                    b.close()
                except Exception:
                    pass
            self._gpiozero_btns = []
        elif self.active_backend == "RPi.GPIO":
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup([self.pin_start, self.pin_reset])
            except Exception:
                pass
        self.is_hardware_available = False

