import uasyncio as asyncio
import time
from machine import Pin, freq

from status_indicator import StatusIndicator, SLEEP
from wifi_manager import WifiManager


class SleepController:
    """Detects sleep-request holds and puts the system into low-power sleep until woken."""
    def __init__(self, sleep_pin: Pin, status: StatusIndicator, wifi: WifiManager, hold_ms=1000, normal_freq=160_000_000, sleep_freq=80_000_000):
        self._sleep_pin = sleep_pin
        self._status = status
        self._wifi = wifi
        self._hold_ms = hold_ms
        self._normal_freq = normal_freq
        self._sleep_freq = sleep_freq

    async def should_sleep(self):
        """Checks whether the sleep pin is held at 0 for `self._hold_ms`."""
        pin = self._sleep_pin

        # If not 0 (1), then VCC is connected to the pin through the resistor with 3.3V and no current,
        # so it's not being pressed
        if pin.value() != 0:
            return False
        # If is 0, then the switch was pressed, connecting the pin to GND,
        # causing current to flow with voltage consumed by the resistor instead of the pin

        # If held for _hold_ms, return True for sleep
        start = time.ticks_ms()
        while pin.value() == 0:
            if time.ticks_diff(time.ticks_ms(), start) >= self._hold_ms:
                self._wait_for_release()
                return True
            await asyncio.sleep_ms(10)
        # Else, return false for no sleep
        return False

    def enter_sleep(self):
        """Saves power by turning off Wi-Fi and lowering CPU frequency, waking up when the `sleep_pin` is 0."""
        print("entering sleep")
        self._wifi.disconnect()
        self._status.state = SLEEP
        self._status.led_off()
        freq(self._sleep_freq)

        pin = self._sleep_pin
        while pin.value() != 0:
            time.sleep_ms(50)

        freq(self._normal_freq)
        print("woke from sleep")
        self._wait_for_release()

    def _wait_for_release(self):
        pin = self._sleep_pin
        while pin.value() == 0:
            time.sleep_ms(10)
        time.sleep_ms(50)
