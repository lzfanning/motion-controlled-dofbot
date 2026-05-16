#!/usr/bin/env python3
import atexit
import json
import signal
import subprocess
import threading
import time
import Arm_Lib

from pathlib import Path
from flask import Flask, jsonify, request
from wifi_manager import WifiManager
from arm_api import arm_api, init_arm_api


_BASE_DIR = Path(__file__).resolve().parent
_MOTION_SCRIPT = _BASE_DIR / "motion_receiver" / "main.py"
_MOTION_WORKDIR = _BASE_DIR / "motion_receiver"
_STATE_PATH = _BASE_DIR / "connectivity_state.json"
_MOTION_STATE_PATH = _BASE_DIR / "motion_state.json"
_INDEX_HTML = (_BASE_DIR / "index.html").read_text()


class MotionProcess:
    """Manages the motion-receiver subprocess lifecycle and autostart preference."""
    def __init__(self, script_path, workdir, state_path):
        self._script_path = script_path
        self._workdir = workdir
        self._state_path = Path(state_path)
        self._proc = None
        self._lock = threading.Lock()

    def get_autostart(self):
        return bool(self._load_state().get("autostart", False))

    def set_autostart(self, enabled):
        state = self._load_state()
        state["autostart"] = bool(enabled)
        self._write_state(state)
        return state["autostart"]

    def _load_state(self):
        try:
            return json.loads(self._state_path.read_text())
        except Exception:
            return {}

    def _write_state(self, state):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def start(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return False, "already running"

            self._proc = subprocess.Popen(
                ["python3", str(self._script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(self._workdir),
                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
            )
            return True, f"started (pid {self._proc.pid})"

    def stop(self):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = None
                return False, "not running"

            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)

            pid = self._proc.pid
            self._proc = None
            return True, f"stopped (pid {pid})"

    def running(self):
        with self._lock:
            return self._proc is not None and self._proc.poll() is None


app = Flask(__name__)
arm = Arm_Lib.Arm_Device()
time.sleep(0.2)

motion = MotionProcess(_MOTION_SCRIPT, _MOTION_WORKDIR, _MOTION_STATE_PATH)
wifi = WifiManager(state_path=_STATE_PATH)

init_arm_api(arm)
app.register_blueprint(arm_api)


@app.route("/", methods=["GET"])
def index():
    return _INDEX_HTML


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify(status="ok")


@app.route("/wifi/status", methods=["GET"])
def wifi_status_route():
    with wifi.lock:
        return jsonify(status="ok", wifi=wifi.wifi_status())


@app.route("/wifi/networks", methods=["GET"])
def wifi_networks_route():
    with wifi.lock:
        state = wifi.load_state()
        return jsonify(status="ok", networks=wifi.cached_scan_results(), scanned_at=state.get("scan_results_at"))


@app.route("/wifi/saved", methods=["GET"])
def wifi_saved_route():
    with wifi.lock:
        return jsonify(status="ok", networks=wifi.saved_wifi_connections(), state=wifi.load_state())


@app.route("/wifi/connect", methods=["POST"])
def wifi_connect_route():
    data = request.get_json(silent=True) or {}
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    hidden = bool(data.get("hidden"))

    if not ssid:
        return jsonify(status="error", message="ssid is required"), 400

    with wifi.lock:
        result = wifi.connect_wifi(ssid, password=password, hidden=hidden)

    if result["ok"]:
        return jsonify(status="ok", wifi=wifi.wifi_status(), connection=result["connection"])
    return jsonify(status="error", message="failed to connect", details=result, wifi=wifi.wifi_status()), 400


@app.route("/wifi/hotspot/start", methods=["POST"])
def wifi_hotspot_start_route():
    with wifi.lock:
        status = wifi.start_hotspot()
    return jsonify(status="ok", wifi=status)


@app.route("/wifi/hotspot/stop", methods=["POST"])
def wifi_hotspot_stop_route():
    with wifi.lock:
        wifi.stop_hotspot()
    return jsonify(status="ok", wifi=wifi.wifi_status())


@app.route("/wifi/recover", methods=["POST"])
def wifi_recover_route():
    with wifi.lock:
        result = wifi.recover_wifi()
    return jsonify(status="ok", result=result, wifi=wifi.wifi_status())


@app.route("/motion/start", methods=["POST"])
def motion_start_route():
    ok, msg = motion.start()
    return jsonify(status="ok" if ok else "noop", message=msg, running=motion.running())


@app.route("/motion/stop", methods=["POST"])
def motion_stop_route():
    ok, msg = motion.stop()
    return jsonify(status="ok" if ok else "noop", message=msg, running=motion.running())


@app.route("/motion/status", methods=["GET"])
def motion_status_route():
    return jsonify(status="ok", running=motion.running(), autostart=motion.get_autostart())


@app.route("/motion/autostart", methods=["GET"])
def motion_autostart_get_route():
    return jsonify(status="ok", autostart=motion.get_autostart())


@app.route("/motion/autostart", methods=["POST"])
def motion_autostart_set_route():
    data = request.get_json(silent=True) or {}
    if "enabled" not in data:
        return jsonify(status="error", message="enabled is required"), 400
    enabled = motion.set_autostart(data["enabled"])
    return jsonify(status="ok", autostart=enabled)


def cleanup():
    motion.stop()


def autostart_motion_if_enabled():
    if motion.get_autostart():
        ok, msg = motion.start()
        print(f"motion autostart: {msg}")


atexit.register(cleanup)
threading.Thread(target=wifi.startup_network_mode, daemon=True).start()
autostart_motion_if_enabled()


def main():
    app.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
