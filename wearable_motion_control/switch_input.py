from machine import Pin
import time

_DEBOUNCE_MS = 40


class Button:
    """Tracks button-like states for a pin with debounce."""
    __slots__ = ("pin", "_was_pressed", "_press_ms", "_held",
                 "_last_ms", "_hold_threshold_ms",
                 "short_pressed", "holding", "hold_started")

    def __init__(self, pin, hold_threshold_ms=300):
        self.pin = pin
        self._was_pressed = False
        self._press_ms = 0
        self._held = False
        self._last_ms = 0
        self._hold_threshold_ms = hold_threshold_ms
        self.short_pressed = False
        self.holding = False
        self.hold_started = False

    @property
    def is_down(self):
        return self.pin.value() == 0

    def update(self, now):
        """Updates hold/short_pressed/hold_started state."""
        is_down = self.is_down
        self.short_pressed = False
        self.hold_started = False

        if is_down and not self._was_pressed:
            if time.ticks_diff(now, self._last_ms) > _DEBOUNCE_MS:
                self._press_ms = now
                self._held = False
        elif is_down and self._was_pressed:
            if not self._held:
                if time.ticks_diff(now, self._press_ms) >= self._hold_threshold_ms:
                    self._held = True
                    self.hold_started = True
        elif not is_down and self._was_pressed:
            if not self._held:
                if time.ticks_diff(now, self._last_ms) > _DEBOUNCE_MS:
                    self.short_pressed = True
                    self._last_ms = now
            else:
                self._last_ms = now

        self._was_pressed = is_down
        self.holding = is_down and self._held


class SwitchInput:
    """Groups three role-based button inputs."""
    def __init__(self, mode_pin=18, forward_pin=20, back_pin=17, hold_threshold_ms=300):
        self.mode = Button(Pin(mode_pin, Pin.IN, Pin.PULL_UP), hold_threshold_ms)
        self.forward = Button(Pin(forward_pin, Pin.IN, Pin.PULL_UP), hold_threshold_ms)
        self.back = Button(Pin(back_pin, Pin.IN, Pin.PULL_UP), hold_threshold_ms)

    def read(self):
        now = time.ticks_ms()
        self.mode.update(now)
        self.forward.update(now)
        self.back.update(now)
