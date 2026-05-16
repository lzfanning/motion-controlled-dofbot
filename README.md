# Motion-Controlled Dofbot

A wearable IMU device that streams angular motion data over Wi-Fi to the [Dofbot](https://github.com/YahboomTechnology/dofbot-Pi), which mirrors the motion in real time and can record and play back animations.

## Network overview
- Wearable -> Dofbot: UDP, port **56001**
- Dofbot web UI and arm HTTP API: TCP, port **5000**
- Setup hotspot (started by the Dofbot, joined by the wearable):
	- SSID: `Dofbot-Setup`
	- Password: `dofbotsetup`
	- Web UI: `http://10.42.0.1:5000/`

---

# Dofbot Motion Control
## Parts
1. [Dofbot](https://github.com/YahboomTechnology/dofbot-Pi)

## Steps
### 1. Clone
``` bash
cd /home/dofbot
git clone <repo-url> dofbot_motion_control
sudo chown -R dofbot:dofbot dofbot_motion_control
```

### 2. Run
#### Manual
``` bash
cd dofbot_motion_control/motion_receiver
python main.py
```
#### Service (includes hotspot)
``` bash
sudo cp dofbot_motion_control/systemd/dofbot-motion-control.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dofbot-motion-control
```
Then start the Motion Receiver from the web interface at `http://<DOFBOT_IP>:5000/`.
### Service boot behavior
If the Dofbot can reach a known Wi-Fi network or is plugged into ethernet, it connects normally. Otherwise it starts a setup hotspot:
1. Connect to the `Dofbot-Setup` Wi-Fi (password `dofbotsetup`).
2. Open `http://10.42.0.1:5000/`.
3. You can add a Wi-Fi network. If you do, the dofbot connects and the hotspot turns off.

## Troubleshooting
- **Wi-Fi buttons in the web UI do nothing:** The `dofbot` user can't run `nmcli` without a password prompt. Verify with `sudo -l -U dofbot`. You should see `NOPASSWD` for either `ALL` or `/usr/bin/nmcli`, which is currently the default on the Pi 4 image provided by yahboom.
- **Security warning**: Ensure the URL starts with `http`, not `https`.

---

# Wearable Motion Control

A MicroPython-based wearable that streams hand orientation to the Dofbot over Wi-Fi. By default it joins the Dofbot's `Dofbot-Setup` hotspot at `10.42.0.1:56001`. To target a different network, see [Configuration](#configuration) below.

## Parts
1. [XIAO-ESP32-C6](https://documentation.espressif.com/esp32-c6_datasheet_en.pdf)
2. [ICM-45686](https://www.mouser.com/catalog/specsheets/TDK_DS_000577_ICM_45686.pdf)
3. 5-axis directional switch
4. 400mAh lipo battery
5. Velcro, glove, 3D print, etc

## Connections

### ICM-45686 (IMU)
**Note**: The IMU currently must face a specific direction for predictable usage. Relative to you when wearing it with your forearm straight ahead, Y (pitch) should point straight down to the ground, and X (roll) should point to your left. See [TODO](#todo).

| XIAO-ESP32-C6 | ICM-45686 |
|---|---|
| 3V3           | 3V3 |
| GND           | GND |
| D6 (GPIO 16)  | CS  |
| D5 (GPIO 23)  | SCL |
| D4 (GPIO 22)  | SDI |
| D3 (GPIO 21)  | SDO |
| D2 (GPIO 2)   | INT |

### 5-axis directional switch (3 of 5 directions used)
| XIAO-ESP32-C6 | Switch | Role      |
| ------------- | ------ | --------- |
| GND           | GND    | N/A       |
| D10 (GPIO 18) | CENTER | `mode`    |
| D9 (GPIO 20)  | LEFT   | `forward` |
| D7 (GPIO 17)  | DOWN   | `back`    |

The code refers to buttons by their role (`mode`, `forward`, `back`) rather than their physical direction, so any 3-button setup works fine. Pin assignments are configurable in `config.json` (see [Configuration](#configuration)).

### Lipo battery
Wire `+` to `+` and `−` to `−`.

## Steps
1. Flash MicroPython firmware
	1. Download [firmware](https://micropython.org/download/ESP32_GENERIC_C6/) and [esptool](https://docs.espressif.com/projects/esptool/en/latest/esp32/)
	2. While plugged into PC, put the ESP32 into bootloader mode
		1. Hold boot
		2. Press reset
		3. Release boot
	3. Use esptool to flash the downloaded firmware
		``` bash
		esptool.py --chip esp32c6 --port /dev/ttyACM0 erase_flash
		esptool.py --chip esp32c6 --port /dev/ttyACM0 --baud 460800 write_flash 0x0 ESP32_GENERIC_C6-<version>.bin
		```
2. Upload `wearable_motion_control` scripts via [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
	- `main.py` is automatically executed after reset.
	- **CLI:**
		``` bash
		mpremote connect /dev/ttyACM0 fs cp -r wearable_motion_control/. :
		```

## Configuration

The wearable reads `config.json` from its filesystem on boot. The version in this repo points at the Dofbot's setup hotspot by default.

``` json
{
    "wifi_ssid": "Dofbot-Setup",
    "wifi_password": "dofbotsetup",
    "dofbot_host": "10.42.0.1",
    "switch_pins": {
        "mode": 18,
        "forward": 20,
        "back": 17
    }
}
```

- **`wifi_ssid` / `wifi_password`**: Network to join. Default is the Dofbot's hotspot.
- **`dofbot_host`**: IP of the Dofbot. Default is the hotspot gateway. If the Dofbot is on a different network, enter the IP shown on the OLED display.
- **`switch_pins`**: GPIO pin for each button role. See [Controls](#controls) for what each role does.

To apply changes, edit `config.json`, upload it, and reset:

``` bash
mpremote connect /dev/ttyACM0 fs cp config.json :
```

## Usage

The wearable boots into IDLE while it joins the Dofbot's hotspot. Once connected, it enters ACTIVE (live motion streaming). Control servo 3 when your forearm is within 22 degrees of the neutral/thumb-up position. Rotate more than 22 degrees clockwise to control servo 4, or more than 22 degrees counterclockwise to control servo 2.

### Status LED
- **Off**: sleeping
- **Slow blink**: idle (connecting to Wi-Fi)
- **Fast blink**: active (live motion streaming)
- **Very fast blink**: recording

### Controls

| State      | Button  | Gesture        | Action                                  |
| ---------- | ------- | -------------- | --------------------------------------- |
| Live       | mode    | tap            | mute (stop streaming, arm returns home) |
| Live       | mode    | hold           | wrist roll (servo 5) mode               |
| Live       | back    | hold           | close gripper                           |
| Live       | forward | hold           | open gripper                            |
| Muted      | mode    | tap            | unmute back into live mode              |
| Muted      | mode    | hold           | start a new recording                   |
| Muted      | forward | tap            | next saved animation                    |
| Muted      | back    | tap            | previous saved animation                |
| Muted      | back    | hold           | delete current animation                |
| Connecting | mode    | long hold (1s) | enter sleep                             |
| Sleeping   | mode    | tap            | wake                                    |

Recorded animations are saved on the Dofbot and persist across reboots.

## Notes
- Would wire differently if done again
	- The pins D0-D6 offer special functionality
		- Could use just one of those ADC pins for the entire 5-axis directional switch via resistor ladder
		- They also allow for waking during a PROPER sleep low power mode (not currently supported in the code)
- Might've been better to use conductive thread for the switch connections
- The legs of the switch are very delicate and should not be bent

## TODO
- An easy way to configure how the quaternion should be mapped no matter the orientation of the IMU
	- Maybe a one-time calibration where you move up/down and then left/right
- Support true sleep mode if the pin supports it
- Hotspot configuration
- More control scheme customization, especially for those with all 5 switch axes working
- Haptic feedback
- Alternative networking solutions like Bluetooth or ESP-NOW