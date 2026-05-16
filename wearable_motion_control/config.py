"""Loads wearable configuration from `config.json`.

`config.json` ships with the repo and defaults to the Dofbot's setup hotspot.
To target a different network (e.g. the Dofbot joined to home Wi-Fi),
edit config.json and re-upload it:
    {
      "wifi_ssid": "MyHomeNetwork",
      "wifi_password": "supersecret",
      "dofbot_host": "192.168.1.42"
    }
"""
import json

_CONFIG_PATH = "config.json"


def load():
    """Returns a dict with wifi_ssid, wifi_password, and dofbot_host."""
    with open(_CONFIG_PATH) as f:
        return json.load(f)
