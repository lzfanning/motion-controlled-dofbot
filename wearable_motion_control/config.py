"""Loads wearable configuration from `config.json`."""
import json

_CONFIG_PATH = "config.json"


def load():
    """Returns a dict with wifi_ssid, wifi_password, and dofbot_host."""
    with open(_CONFIG_PATH) as f:
        return json.load(f)
