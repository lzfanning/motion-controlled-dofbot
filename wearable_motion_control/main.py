import uasyncio as asyncio

import config
from protocol import UDP_PORT
from status_indicator import StatusIndicator, IDLE, ACTIVE
from wifi_manager import WifiManager
from switch_input import SwitchInput
from sleep_controller import SleepController
from motion_sync import MotionSync


async def main():
    cfg = config.load()

    status = StatusIndicator()

    # Runs the status function in a task to avoid blocking this main function
    asyncio.create_task(status.run())

    pins = cfg["switch_pins"]
    switch_input = SwitchInput(
        mode_pin=pins["mode"],
        forward_pin=pins["forward"],
        back_pin=pins["back"],
    )
    wifi = WifiManager(cfg["wifi_ssid"], cfg["wifi_password"])
    sleep_ctrl = SleepController(switch_input.mode.pin, status, wifi)

    while True:
        status.state = IDLE

        # Keeps trying to connect to wifi while also checking whether should sleep
        wlan = await wifi.connect(sleep_ctrl.should_sleep)

        # If None, then should_sleep evaluated to True and should enter sleep
        if wlan is None:
            sleep_ctrl.enter_sleep()
            continue

        motion = MotionSync(
            cfg["dofbot_host"],
            UDP_PORT,
            switch_input,
            status,
            gyro_bias_calibration=cfg.get("gyro_bias_calibration"),
        )
        status.state = ACTIVE
        await motion.run(wlan=wlan)


asyncio.run(main())
