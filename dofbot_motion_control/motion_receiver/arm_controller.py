import math
import Arm_Lib

from orientation import clamp, angle_delta


class Servo:
    """Tracks a servo target position and smoothed output within limits."""
    __slots__ = ("default_pos", "min_pos", "max_pos", "current_pos", "smoothed")

    def __init__(self, default_pos, min_pos, max_pos):
        self.default_pos = default_pos
        self.min_pos = min_pos
        self.max_pos = max_pos
        self.current_pos = default_pos
        self.smoothed = default_pos

    @property
    def rounded_pos(self):
        return int(round(self.smoothed))

    def reset(self):
        self.current_pos = self.default_pos
        self.smoothed = self.default_pos

    def move(self, delta):
        self.current_pos = clamp(self.current_pos + delta, self.min_pos, self.max_pos)

    def smooth(self, alpha):
        self.smoothed += alpha * (self.current_pos - self.smoothed)


# Servo definitions
base = Servo(default_pos=90.0, min_pos=5.0, max_pos=175.0)
shoulder = Servo(default_pos=95.0, min_pos=0.0, max_pos=180.0)
elbow = Servo(default_pos=20.0, min_pos=0.0, max_pos=180.0)
wrist = Servo(default_pos=45.0, min_pos=0.0, max_pos=180.0)
servo5 = Servo(default_pos=90.0, min_pos=0.0, max_pos=180.0)

_SERVOS = (base, shoulder, elbow, wrist, servo5)

# Gripper (no smoothing, step-based, separate write)
GRIP_OPEN = 90
GRIP_CLOSED = 180
GRIP_STEP = 5
GRIP_MOVE_MS = 80

# Tuning
ANGLE_SCALE = 57.3

INVERT_YAW = False
INVERT_PITCH = False
SMOOTH_ALPHA = 0.9
WRITE_PERIOD_S = 0.011
MOVE_TIME_MS = 80

# Servo 5 hold
_SERVO5_HOLD_TIMEOUT_S = 0.2


class ArmController:
    """Controls servos of the arm and applies motion of 3D orientation angles."""
    def __init__(self, arm: Arm_Lib.Arm_Device):
        self._arm = arm
        self._servo5_hold = False
        self._servo5_hold_time = 0.0
        self._last_write_time = 0.0
        self._grip_pos = GRIP_OPEN
        self._reset_positions()

    def go_home(self, move_ms=500):
        self._reset_positions()
        self._write_all(move_ms)

    def grip_step_close(self):
        """Tightens the grip by one step."""
        self._grip_pos = clamp(self._grip_pos + GRIP_STEP, GRIP_OPEN, GRIP_CLOSED)
        self._arm.Arm_serial_servo_write(6, int(self._grip_pos), GRIP_MOVE_MS)

    def grip_step_open(self):
        """Loosens the grip by one step."""
        self._grip_pos = clamp(self._grip_pos - GRIP_STEP, GRIP_OPEN, GRIP_CLOSED)
        self._arm.Arm_serial_servo_write(6, int(self._grip_pos), GRIP_MOVE_MS)

    def set_servo5_hold(self, now):
        self._servo5_hold = True
        self._servo5_hold_time = now

    def apply_motion(self, d_yaw, d_pitch, d_roll, roll, zero_roll, now):
        """Maps orientation deltas to servo positions."""
        # Auto-release servo5 hold if no S5H received recently
        if self._servo5_hold and (now - self._servo5_hold_time > _SERVO5_HOLD_TIMEOUT_S):
            self._servo5_hold = False

        pitch_sign = -1.0 if INVERT_PITCH else 1.0
        pitch_delta = pitch_sign * d_pitch * ANGLE_SCALE

        if self._servo5_hold:
            roll_delta = -d_roll * ANGLE_SCALE
            servo5.move(roll_delta)
        else:
            yaw_sign = -1.0 if INVERT_YAW else 1.0
            base_delta = yaw_sign * d_yaw * ANGLE_SCALE

            roll_from_center = angle_delta(roll, zero_roll)
            roll_deg = math.degrees(roll_from_center)

            if roll_deg > 22.0:
                shoulder_w, elbow_w, wrist_w = 0.0, 0.0, 1.0
            elif roll_deg < -22.0:
                shoulder_w, elbow_w, wrist_w = 1.0, 0.0, 0.0
            else:
                shoulder_w, elbow_w, wrist_w = 0.0, 1.0, 0.0

            base.move(base_delta)
            shoulder.move(pitch_delta * shoulder_w)
            elbow.move(pitch_delta * elbow_w)
            wrist.move(pitch_delta * wrist_w)

        for s in _SERVOS:
            s.smooth(SMOOTH_ALPHA)

    def write_if_due(self, now):
        """Writes servo positions to hardware when enough time passes."""
        if now - self._last_write_time < WRITE_PERIOD_S:
            return False
        self._write_all(MOVE_TIME_MS)
        self._last_write_time = now
        return True

    def snapshot(self):
        """Returns current joint positions as a list of 6 integers."""
        return [s.rounded_pos for s in _SERVOS] + [int(round(self._grip_pos))]

    def write_joints(self, joints, move_ms=None):
        """Writes arbitrary joint positions to hardware."""
        if move_ms is None:
            move_ms = MOVE_TIME_MS
        self._arm.Arm_serial_servo_write6_array(list(joints), move_ms)

    def _write_all(self, move_ms):
        self._arm.Arm_serial_servo_write6_array(self.snapshot(), move_ms)

    def _reset_positions(self):
        for s in _SERVOS:
            s.reset()
        self._grip_pos = GRIP_OPEN
        self._servo5_hold = False
