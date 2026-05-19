import network
import uasyncio as asyncio


class WifiManager:
    """Connects to a configured Wi-Fi network with retry and cancellation support."""
    def __init__(self, ssid, password):
        self._ssid = ssid
        self._password = password
        self._wlan = network.WLAN(network.STA_IF)

    async def connect(self, should_cancel) -> network.WLAN | None:
        """Connects with retries, returning None if `should_cancel` evaluates to True."""
        while True:
            if await should_cancel():
                return None

            try:
                self._wlan.disconnect()
            except Exception:
                pass

            self._wlan.active(False)
            await asyncio.sleep(0.5)

            self._wlan.active(True)
            self._wlan.config(pm=0)
            await asyncio.sleep(0.5)

            print("connecting to wifi...")
            self._wlan.connect(self._ssid, self._password)

            last_status = None
            for _ in range(24):
                if await should_cancel():
                    return None

                if self._wlan.isconnected():
                    self._wlan.config(pm=0, reconnects=0)
                    print("wifi connected, pm off, reconnects off")
                    print("ip:", self._wlan.ifconfig()[0])
                    return self._wlan

                try:
                    s = self._wlan.status()
                except Exception:
                    s = None

                if s != last_status:
                    print("wifi status:", s)
                    last_status = s

                await asyncio.sleep(0.5)

            print("wifi failed, retrying")

    def disconnect(self):
        try:
            self._wlan.disconnect()
        except Exception:
            pass
        self._wlan.active(False)
