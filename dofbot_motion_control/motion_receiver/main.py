import time
import Arm_Lib

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
from udp_listener import UDPListener
from orientation import OrientationTracker
from arm_controller import ArmController
from animation import Animation
from animation_store import AnimationStore
from net_stats import NetStats


PACKET_TIMEOUT_S = 0.6

IDLE = "idle"
LIVE = "live"
RECORDING = "recording"
PLAYBACK = "playback"


class MotionReceiver:
    """Runs the receive loop and applies commands and motion to the arm."""
    def __init__(self):
        self.arm = Arm_Lib.Arm_Device()
        self.listener = UDPListener()
        self.orientation = OrientationTracker()
        self.controller = ArmController(self.arm)
        self.stats = NetStats()
        self.store = AnimationStore()
        self.store.load()

        self._mode = IDLE
        self._last_packet_time = 0.0
        self._timed_out = False

        self._recording = None
        self._last_record_time = 0.0

        self._playback_anim = None
        self._playback_index = 0
        self._playback_next_time = 0.0

    def run(self):
        self.controller.go_home()
        time.sleep(0.6)

        while True:
            now = time.monotonic()
            latest_motion = None

            for kind, data, receive_time in self.listener.receive():
                if kind == "cmd":
                    self._handle_command(data, receive_time, now)
                elif kind == "motion":
                    latest_motion = self._handle_motion_packet(data, receive_time)

            self._process_motion(latest_motion)
            self._capture_recording_frame(latest_motion)
            self._playback(now)
            self._check_timeout_and_write(now)

    def _handle_command(self, command, receive_time, now):
        if command == CMD_RESET:
            self._handle_reset()
        elif command == CMD_CALIBRATE:
            self._handle_calibrate()
        elif command == CMD_RECORD:
            self._handle_record()
        elif command == CMD_ANIM_NEXT:
            self._handle_anim_next(now)
        elif command == CMD_ANIM_PREV:
            self._handle_anim_prev(now)
        elif command == CMD_ANIM_DELETE:
            self._handle_anim_delete(now)
        elif command == CMD_SERVO_HOLD:
            if self._mode in (LIVE, RECORDING):
                self.controller.set_servo5_hold(receive_time)
        elif command == CMD_GRIP_CLOSE:
            if self._mode in (LIVE, RECORDING):
                self.controller.grip_step_close()
        elif command == CMD_GRIP_OPEN:
            if self._mode in (LIVE, RECORDING):
                self.controller.grip_step_open()

    def _handle_reset(self):
        if self._mode == RECORDING:
            self._finish_recording()

        self._stop_playback()

        self.stats.print_summary("before reset")
        print("motion receiver: RESET -- returning to home")

        self.orientation.reset()
        self.controller.go_home()
        time.sleep(0.5)

        self.stats.reset()
        self._mode = IDLE
        self._timed_out = False

    def _handle_calibrate(self):
        # CAL shouldn't be received while recording
        if self._mode == RECORDING:
            return

        self._stop_playback()

        print("motion receiver: CALIBRATE -- entering live mode")
        self._start_session(LIVE)

    def _handle_record(self):
        # Ignore duplicate REC
        if self._mode == RECORDING:
            return

        self._stop_playback()

        print("motion receiver: RECORD -- entering recording mode")

        self._recording = Animation()
        self._last_record_time = 0.0
        self._start_session(RECORDING)

    def _start_session(self, mode):
        """Begins a LIVE or RECORDING session with fresh orientation and timeout state."""
        self.orientation.reset()
        self._mode = mode
        self._timed_out = False
        self._last_packet_time = 0.0

    def _handle_anim_next(self, now):
        if self._mode not in (IDLE, PLAYBACK):
            return

        anim = self.store.next()
        self._start_animation(anim, now)

    def _handle_anim_prev(self, now):
        if self._mode not in (IDLE, PLAYBACK):
            return

        anim = self.store.prev()
        self._start_animation(anim, now)

    def _handle_anim_delete(self, now):
        if self._mode != PLAYBACK:
            return

        anim = self.store.delete_current()

        if anim is None:
            print("motion receiver: no animations remaining")
            self._stop_playback()
            self.controller.go_home()
            self._mode = IDLE
            return

        self._start_animation(anim, now)

    def _start_animation(self, anim, now):
        if anim is None:
            print("motion receiver: no animations stored")
            return

        print(f"motion receiver: animation {self.store.index + 1}/{self.store.count} "
              f"({len(anim)} frames, {anim.duration_s:.1f}s)")

        self._playback_anim = anim
        self._playback_index = 0
        self._playback_next_time = now
        self._mode = PLAYBACK

    def _stop_playback(self):
        self._playback_anim = None
        self._playback_index = 0
        self._playback_next_time = 0.0

    def _handle_motion_packet(self, data, receive_time):
        seq, rv, grv = data
        self.stats.record(seq, receive_time)

        if self._timed_out:
            print("motion receiver: stream recovered")
            self._timed_out = False

        return rv, grv, receive_time

    def _process_motion(self, latest_motion):
        if self._mode not in (LIVE, RECORDING) or latest_motion is None:
            return

        rv, grv, now = latest_motion

        if grv is None and rv is None:
            return

        rotation = grv if grv is not None else rv

        if not self.orientation.calibrated:
            self.orientation.calibrate(rv, grv)

        deltas = self.orientation.update(rotation)

        if deltas is not None:
            d_yaw, d_pitch, d_roll, roll = deltas
            self.controller.apply_motion(d_yaw, d_pitch, d_roll, roll, self.orientation.zero_roll, now)

        self._last_packet_time = now

    def _capture_recording_frame(self, latest_motion):
        if self._mode != RECORDING or latest_motion is None:
            return

        _, _, now = latest_motion

        if self._last_record_time > 0.0:
            dt_ms = int((now - self._last_record_time) * 1000)
            self._recording.add_frame(dt_ms, self.controller.snapshot())

        self._last_record_time = now

    def _playback(self, now):
        if self._mode != PLAYBACK or self._playback_anim is None:
            return

        if now - self._playback_next_time > 0.5:
            self._playback_next_time = now

        if now < self._playback_next_time:
            return

        _, joints = self._playback_anim.frames[self._playback_index]
        self.controller.write_joints(joints)

        self._playback_index += 1

        if self._playback_index >= len(self._playback_anim):
            self._playback_index = 0

        next_dt_ms = self._playback_anim.frames[self._playback_index][0]
        self._playback_next_time += next_dt_ms / 1000.0

    def _check_timeout_and_write(self, now):
        if self._mode not in (LIVE, RECORDING):
            return

        if now - self._last_packet_time > PACKET_TIMEOUT_S:
            if not self._timed_out and self._last_packet_time > 0.0:
                self.stats.print_summary("before timeout")
                print(f"motion receiver: stream timeout after {PACKET_TIMEOUT_S:.2f}s")
                self._timed_out = True
                self.stats.reset()
            return

        self.controller.write_if_due(now)

    def _finish_recording(self):
        if self._recording is None or len(self._recording) < 2:
            print("motion receiver: recording too short, discarding")
            self._recording = None
            return

        print(f"motion receiver: saving recording "
              f"({len(self._recording)} frames, {self._recording.duration_s:.1f}s)")

        self.store.add(self._recording)
        self._recording = None


def main():
    receiver = MotionReceiver()
    receiver.run()


if __name__ == "__main__":
    main()
