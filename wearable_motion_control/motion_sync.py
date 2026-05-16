import uasyncio as asyncio
import gc
import time

from protocol import (
    CMD_RESET,
    CMD_CALIBRATE,
    CMD_SERVO_HOLD,
    CMD_GRIP_CLOSE,
    CMD_GRIP_OPEN,
    CMD_RECORD,
    CMD_ANIM_NEXT,
    CMD_ANIM_PREV,
    CMD_ANIM_DELETE,
)
from imu import IMU
from mahony_filter import MahonyFilter
from udp_sender import UDPSender
from switch_input import SwitchInput
from status_indicator import StatusIndicator, ACTIVE, IDLE, RECORDING

_IMU_HZ = 100
_CMD_REPEAT_MS = 80
_GC_MAX = 10


class MotionSync:
    """Reads IMU motion and synchronizes it to a robot arm."""
    def __init__(self, host, port, switch_input: SwitchInput, status: StatusIndicator | None = None):
        self._imu = IMU()
        self._filter = MahonyFilter()
        self._sender = UDPSender(host, port)
        self._switch_input = switch_input
        self._status = status

        self._muted = False
        self._recording = False
        self._last_cmd_ms = 0
        self._last_ms = time.ticks_ms()

    async def run(self, wlan=None):
        """Streams motion data and sends commands."""
        self._init_and_calibrate()
        gc.collect()
        gc_counter = 0

        period_ms = int(1000 / _IMU_HZ)
        self._last_ms = time.ticks_ms()
        next_tick = time.ticks_add(self._last_ms, period_ms)

        print("motion sync running")
        print("live: mode tap = mute, mode hold = servo5, back = grab, forward = open")
        print("muted: mode tap = unmute, mode hold = record")
        print("muted: forward tap = next anim, back tap = prev anim, back hold = delete anim")
        print("INT mode:", "enabled" if self._imu.interrupt_enabled else "polling")

        while True:
            now = time.ticks_ms()

            if wlan is not None and not wlan.isconnected():
                print("wifi lost, stopping motion sync")
                self._muted = True
                return

            sw = self._switch_input
            sw.read()

            if sw.mode.short_pressed:
                self._toggle_mute()

            self._handle_commands(sw)

            if not self._muted:
                await self._wait_for_data_ready(next_tick)

                dt = self._compute_dt(_IMU_HZ)
                gx, gy, gz, ax, ay, az = self._imu.read_motion()
                self._filter.update(gx, gy, gz, ax, ay, az, dt)

                try:
                    qw, qx, qy, qz = self._filter.remapped_quaternion
                    self._sender.send_motion(gx, gy, gz, ax, ay, az, qw, qx, qy, qz)
                except OSError:
                    pass
                gc_counter += 1
                if gc_counter >= _GC_MAX:
                    gc.collect()
                    gc_counter = 0
            else:
                self._last_ms = now

            remaining = time.ticks_diff(next_tick, time.ticks_ms())
            if remaining > 0:
                await asyncio.sleep_ms(remaining)
                next_tick = time.ticks_add(next_tick, period_ms)
            else:
                next_tick = time.ticks_add(time.ticks_ms(), period_ms)

    def _init_and_calibrate(self):
        self._imu.init()
        self._recalibrate()

    def _recalibrate(self):
        avg_accel = self._imu.calibrate()

        if avg_accel is not None:
            self._filter.reset_from_accel(*avg_accel)
            self._imu.clear_data_ready()
            self._filter.settle(self._imu)
        else:
            print("skipping filter reset")

    def _toggle_mute(self):
        if not self._muted:
            # Mute
            self._muted = True
            self._recording = False
            gc.collect()
            print("muted -> RST")
            self._sender.send_command(CMD_RESET)
            self._update_status()
        else:
            # Unmute
            self._muted = False
            self._recording = False
            gc.collect()
            print("live -> recalibrating + CAL")
            self._recalibrate()
            self._sender.send_command(CMD_CALIBRATE)
            self._update_status()

    def _start_recording(self):
        """Unmutes into recording mode (long hold while muted). Sends the `CMD_RECORD` command."""
        self._muted = False
        self._recording = True
        gc.collect()
        print("recording -> recalibrating + REC")
        self._recalibrate()
        self._sender.send_command(CMD_RECORD)
        self._update_status()

    def _update_status(self):
        if self._status is None:
            return
        if self._recording:
            self._status.state = RECORDING
        elif not self._muted:
            self._status.state = ACTIVE
        else:
            self._status.state = IDLE

    def _handle_commands(self, sw):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_cmd_ms) < _CMD_REPEAT_MS:
            return

        if self._muted:
            if sw.mode.hold_started:
                self._start_recording()
                self._last_cmd_ms = now
            elif sw.back.hold_started:
                self._sender.send_command(CMD_ANIM_DELETE)
                self._last_cmd_ms = now
            elif sw.back.short_pressed:
                self._sender.send_command(CMD_ANIM_PREV)
                self._last_cmd_ms = now
            elif sw.forward.short_pressed:
                self._sender.send_command(CMD_ANIM_NEXT)
                self._last_cmd_ms = now
        else:
            if sw.mode.holding:
                self._sender.send_command(CMD_SERVO_HOLD)
                self._last_cmd_ms = now
            elif sw.back.is_down:
                self._sender.send_command(CMD_GRIP_CLOSE)
                self._last_cmd_ms = now
            elif sw.forward.is_down:
                self._sender.send_command(CMD_GRIP_OPEN)
                self._last_cmd_ms = now

    async def _wait_for_data_ready(self, next_tick):
        if not self._imu.interrupt_enabled:
            return

        while not self._imu.data_ready:
            remaining = time.ticks_diff(next_tick, time.ticks_ms())
            if remaining <= 0:
                break
            await asyncio.sleep_ms(1)

        if self._imu.data_ready:
            self._imu.clear_data_ready()

    def _compute_dt(self, hz):
        now = time.ticks_ms()
        dt = time.ticks_diff(now, self._last_ms) / 1000.0
        self._last_ms = now
        if dt <= 0 or dt > 0.1:
            dt = 1.0 / hz
        return dt
