from machine import Pin
import uasyncio as asyncio

SLEEP = 0
IDLE = 1
ACTIVE = 2
RECORDING = 3

_BLINK_RATES = {
    SLEEP: None,
    IDLE: 1,
    ACTIVE: 0.1,
    RECORDING: 0.04,
}


class StatusIndicator:
    """Displays system state using LED blink loop."""
    def __init__(self, led_pin=15):
        self._state = IDLE
        self._led = Pin(led_pin, Pin.OUT)

    @property
    def state(self):
        return self._state
    @state.setter
    def state(self, state):
        self._state = state

    def led_off(self):
        self._led.value(1)

    async def run(self):
        """Runs the LED blink loop for the current state."""
        while True:
            rate = _BLINK_RATES.get(self._state)
            if rate is None:
                self._led.value(1)
                await asyncio.sleep(1)
            else:
                self._led.value(0)
                await asyncio.sleep(rate)
                self._led.value(1)
                await asyncio.sleep(rate)
