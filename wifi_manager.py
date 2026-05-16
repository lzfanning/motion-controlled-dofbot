import json
import subprocess
import threading
import time
import traceback

from pathlib import Path


_HOTSPOT_NAME = "dofbot-hotspot"
_HOTSPOT_SSID = "Dofbot-Setup"
_HOTSPOT_PASSWORD = "dofbotsetup"
_HOTSPOT_CHANNEL = "6"
_HOTSPOT_BAND = "bg"
_HOTSPOT_ADDRESS = "10.42.0.1/24"

_NETWORK_WAIT_S = 15
_BOOT_SCAN_ATTEMPTS = 2
_BOOT_SCAN_PAUSE_S = 3
_STARTUP_ATTEMPTS = 12
_STARTUP_PAUSE_S = 10
_STARTUP_INITIAL_DELAY_S = 5
_REMEMBERED_UUIDS_MAX = 10


class WifiManager:
    """Manages Wi-Fi station connections and the fallback setup hotspot."""
    def __init__(self, state_path):
        self._state_path = Path(state_path)
        self.lock = threading.Lock()

    def startup_network_mode(self):
        """Brings up the best available network mode on boot: ethernet, saved Wi-Fi, or hotspot."""
        time.sleep(_STARTUP_INITIAL_DELAY_S)

        for attempt in range(1, _STARTUP_ATTEMPTS + 1):
            with self.lock:
                try:
                    if self._try_startup_attempt(attempt):
                        return
                except Exception as exc:
                    self._log(f"startup attempt {attempt} crashed: {exc}")
                    self._log(traceback.format_exc())
            time.sleep(_STARTUP_PAUSE_S)

        self._log("startup attempts exhausted")

    def wifi_status(self):
        """Returns a dict summarizing current station, hotspot, ethernet, and device state."""
        station = self.station_connection()
        hotspot = self.hotspot_connection()
        return {
            "station_connected": bool(station),
            "hotspot_active": bool(hotspot),
            "ethernet_connected": self.ethernet_connected(),
            "station": station,
            "hotspot": hotspot,
            "device": self._wifi_device_status(),
            "ips": self._wifi_ips(),
            "saved_networks": len(self.saved_wifi_connections()),
            "scan_results": len(self.cached_scan_results()),
            "hotspot_ssid": _HOTSPOT_SSID,
            "hotspot_password": _HOTSPOT_PASSWORD,
        }

    def station_connection(self):
        """Returns the active non-hotspot Wi-Fi connection dict, or None."""
        active = self._active_wifi_connection()
        if active and active.get("name") != _HOTSPOT_NAME and active.get("mode") != "ap":
            return active
        return None

    def hotspot_connection(self):
        """Returns the active hotspot connection dict, or None."""
        active = self._active_wifi_connection()
        if active and (active.get("name") == _HOTSPOT_NAME or active.get("mode") == "ap"):
            return active
        return None

    def ethernet_connected(self):
        result = self._run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], check=False)
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "eth0" and parts[1] == "ethernet" and parts[2] == "connected":
                return True
        return False

    def connect_wifi(self, ssid, password="", hidden=False):
        """Connects to the given SSID, falling back to the previous network or hotspot on failure."""
        previous = self.station_connection()
        self.stop_hotspot()
        self._ensure_client_profile(ssid, password=password, hidden=hidden)
        result = self._run_nmcli(["connection", "up", ssid], timeout=_NETWORK_WAIT_S, check=False)
        active = self._wait_for_station(ssid=ssid, timeout=_NETWORK_WAIT_S)

        if active:
            self._remember_connection(active)
            return {"ok": True, "connection": active, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}

        if previous and previous.get("uuid"):
            self._bring_up_connection(previous["uuid"])
        else:
            self.start_hotspot()

        return {"ok": False, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}

    def recover_wifi(self, exclude=None, visible_ssids=None):
        """Tries each saved network in last-good-first order. Falls back to hotspot."""
        exclude = set(exclude or [])
        visible_ssids = set(visible_ssids or [])
        candidates = self._recover_candidates(exclude, visible_ssids)

        saved_by_uuid = {item["uuid"]: item for item in self.saved_wifi_connections() if item.get("uuid")}

        for uuid in candidates:
            item = saved_by_uuid.get(uuid, {})
            self._log(f"trying saved wifi {item.get('ssid') or uuid}")

            if self._bring_up_connection(uuid):
                active = self.station_connection()
                self._remember_connection(active)
                return {"recovered": True, "connection": active}

        status = self.start_hotspot()
        return {"recovered": False, "hotspot": status.get("hotspot")}

    def start_hotspot(self):
        self._ensure_hotspot_profile()
        station = self.station_connection()
        if station:
            self._run_nmcli(["connection", "down", station["name"]], check=False, timeout=_NETWORK_WAIT_S)
        self._run_nmcli(["connection", "up", _HOTSPOT_NAME], timeout=_NETWORK_WAIT_S, check=False)
        return self.wifi_status()

    def stop_hotspot(self):
        if self.hotspot_connection():
            self._run_nmcli(["connection", "down", _HOTSPOT_NAME], check=False, timeout=_NETWORK_WAIT_S)

    def saved_wifi_connections(self):
        """Returns a list of saved non-hotspot Wi-Fi connections, newest first."""
        result = self._run_nmcli(
            ["-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP-REAL", "connection", "show"],
            check=False,
        )
        items = []
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 5:
                continue

            name, uuid, kind, autoconnect = parts[0], parts[1], parts[2], parts[3]
            last_seen = ":".join(parts[4:])

            if kind != "802-11-wireless" or name == _HOTSPOT_NAME:
                continue

            mode = self._run_nmcli(["-g", "802-11-wireless.mode", "connection", "show", name], check=False).stdout.strip()
            if mode == "ap":
                continue

            ssid = self._run_nmcli(["-g", "802-11-wireless.ssid", "connection", "show", name], check=False).stdout.strip() or name
            items.append({
                "name": name,
                "uuid": uuid,
                "ssid": ssid,
                "autoconnect": autoconnect == "yes",
                "last_seen": last_seen,
            })

        items.sort(key=lambda x: x["last_seen"], reverse=True)
        return items

    def cached_scan_results(self):
        return self.load_state().get("scan_results", [])

    def load_state(self):
        try:
            return json.loads(self._state_path.read_text())
        except Exception:
            return {"last_good_uuids": []}

    def _try_startup_attempt(self, attempt):
        """Returns True if a usable network mode is established."""
        self._log(f"startup attempt {attempt}")

        if self.ethernet_connected():
            if self.hotspot_connection():
                self.stop_hotspot()
            self._log("ethernet connected; hotspot off")
            return True

        active_station = self.station_connection()
        if active_station and self._wifi_ips():
            if self.hotspot_connection():
                self.stop_hotspot()
            self._remember_connection(active_station)
            self._log(f"station connected to {active_station.get('ssid')}; hotspot off")
            return True

        if self.hotspot_connection():
            self._log("hotspot already active")
            return True

        visible_ssids = self._boot_scan_visible_ssids()

        try:
            result = self.recover_wifi(visible_ssids=visible_ssids)
            if result.get("recovered"):
                active_station = self._wait_for_station(timeout=_NETWORK_WAIT_S)
                if active_station and self._wifi_ips():
                    self._remember_connection(active_station)
                    self._log(f"recovered wifi {active_station.get('ssid')}")
                    return True
                self._log("recovery reported success without usable IP")
        except Exception as exc:
            self._log(f"recover_wifi failed: {exc}")

        status = self.start_hotspot()
        if status.get("hotspot_active"):
            self._log("hotspot started")
            return True

        self._log("hotspot start did not become active")
        return False

    def _boot_scan_visible_ssids(self):
        try:
            scanned = self._boot_scan_networks()
            visible = {item.get("ssid") for item in scanned if item.get("ssid")}
            self._log(f"boot scan found {len(visible)} visible networks")
            return visible
        except Exception as exc:
            self._store_scan_results([])
            self._log(f"boot scan failed: {exc}")
            return set()

    def _recover_candidates(self, exclude, visible_ssids):
        """Returns saved Wi-Fi UUIDs in priority order, filtered by exclude/visible."""
        state = self.load_state()
        saved = self.saved_wifi_connections()
        saved_by_uuid = {item["uuid"]: item for item in saved if item.get("uuid")}

        candidates = []
        seen = set()

        def consider(uuid, item):
            if not uuid or uuid in seen or not item:
                return
            if item.get("ssid") in exclude or item.get("name") in exclude:
                return
            if visible_ssids and item.get("ssid") not in visible_ssids:
                return
            seen.add(uuid)
            candidates.append(uuid)

        for uuid in state.get("last_good_uuids", []):
            consider(uuid, saved_by_uuid.get(uuid))

        for item in saved:
            consider(item.get("uuid"), item)

        return candidates

    def _boot_scan_networks(self):
        scanned = []
        for _ in range(_BOOT_SCAN_ATTEMPTS):
            self._run_nmcli(["device", "wifi", "rescan"], check=False)
            time.sleep(_BOOT_SCAN_PAUSE_S)
            scanned = self._scan_networks()
            if scanned:
                break
        self._store_scan_results(scanned)
        return scanned

    def _scan_networks(self):
        result = self._run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"], check=False)
        items = []
        seen = set()
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 3:
                continue
            ssid = parts[0].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            items.append({
                "ssid": ssid,
                "signal": parts[1].strip(),
                "security": ":".join(parts[2:]).strip(),
            })
        return items

    def _store_scan_results(self, results):
        state = self.load_state()
        state["scan_results"] = results
        state["scan_results_at"] = int(time.time())
        self._write_state(state)

    def _remember_connection(self, connection):
        if not connection or not connection.get("uuid"):
            return
        state = self.load_state()
        uuids = [connection["uuid"]]
        uuids.extend(uuid for uuid in state.get("last_good_uuids", []) if uuid != connection["uuid"])
        state["last_good_uuids"] = uuids[:_REMEMBERED_UUIDS_MAX]
        self._write_state(state)

    def _write_state(self, state):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def _wifi_ips(self):
        result = self._run_nmcli(["-g", "IP4.ADDRESS", "device", "show", "wlan0"], check=False)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _wifi_device_status(self):
        result = self._run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], check=False)
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == "wlan0":
                return {
                    "device": parts[0],
                    "type": parts[1],
                    "state": parts[2],
                    "connection": ":".join(parts[3:]),
                }
        return None

    def _active_wifi_connection(self):
        result = self._run_nmcli(["-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"], check=False)
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 4:
                continue
            name, uuid, kind, device = parts[0], parts[1], parts[2], parts[3]
            if kind != "802-11-wireless" or device != "wlan0":
                continue
            mode = self._run_nmcli(["-g", "802-11-wireless.mode", "connection", "show", name], check=False).stdout.strip()
            ssid = self._run_nmcli(["-g", "802-11-wireless.ssid", "connection", "show", name], check=False).stdout.strip() or name
            return {
                "name": name,
                "uuid": uuid,
                "device": device,
                "mode": mode,
                "ssid": ssid,
            }
        return None

    def _wait_for_station(self, ssid=None, timeout=_NETWORK_WAIT_S):
        deadline = time.time() + timeout
        while time.time() < deadline:
            active = self.station_connection()
            if active and (ssid is None or active.get("ssid") == ssid or active.get("name") == ssid):
                if self._wifi_ips():
                    return active
            time.sleep(1)
        return None

    def _bring_up_connection(self, uuid):
        result = self._run_nmcli(["connection", "up", uuid], timeout=_NETWORK_WAIT_S, check=False)
        self._log(result.stdout.strip())
        if result.returncode == 0:
            return self._wait_for_station(timeout=_NETWORK_WAIT_S) is not None
        return False

    def _ensure_client_profile(self, ssid, password="", hidden=False):
        saved = {item["name"]: item for item in self.saved_wifi_connections()}
        if ssid in saved:
            self._run_nmcli(["connection", "modify", ssid, "802-11-wireless.hidden", "yes" if hidden else "no"], check=False)
            if password:
                self._run_nmcli(["connection", "modify", ssid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password], check=False)
            return

        args = ["device", "wifi", "connect", ssid]
        if password:
            args.extend(["password", password])
        if hidden:
            args.extend(["hidden", "yes"])
        self._run_nmcli(args, timeout=_NETWORK_WAIT_S, check=False)

    def _ensure_hotspot_profile(self):
        existing = {item["name"] for item in self.saved_wifi_connections()}
        if _HOTSPOT_NAME not in existing:
            self._run_nmcli([
                "connection", "add",
                "type", "wifi",
                "ifname", "wlan0",
                "con-name", _HOTSPOT_NAME,
                "autoconnect", "no",
                "ssid", _HOTSPOT_SSID,
            ], check=False)

        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "802-11-wireless.mode", "ap"], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "802-11-wireless.band", _HOTSPOT_BAND], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "802-11-wireless.channel", _HOTSPOT_CHANNEL], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "wifi-sec.key-mgmt", "wpa-psk"], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "wifi-sec.psk", _HOTSPOT_PASSWORD], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "ipv4.method", "shared"], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "ipv4.addresses", _HOTSPOT_ADDRESS], check=False)
        self._run_nmcli(["connection", "modify", _HOTSPOT_NAME, "ipv6.method", "ignore"], check=False)

    @staticmethod
    def _run_nmcli(args, timeout=10, check=True):
        return subprocess.run(
            ["sudo", "-n", "nmcli", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    @staticmethod
    def _log(message):
        print(f"wifi manager: {message}")
