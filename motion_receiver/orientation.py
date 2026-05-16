"""Quaternion math utilities and orientation calibration."""
import math
from typing import Optional, Tuple


def clamp(v, min_v, max_v):
    return min_v if v < min_v else max_v if v > max_v else v


def angle_delta(a, b):
    """Returns the shortest-path difference a-b, wrapped to [-pi, pi]."""
    d = a - b
    while d > math.pi:
        d -= 2.0 * math.pi
    while d < -math.pi:
        d += 2.0 * math.pi
    return d


def quat_inverse(q):
    """Returns the inverse of a unit quaternion (x,y,z,w)."""
    return (-q[0], -q[1], -q[2], q[3])


def quat_multiply(a, b):
    """Hamilton product of two quaternions (x,y,z,w)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_normalize(q):
    x, y, z, w = q
    m = math.sqrt(x * x + y * y + z * z + w * w)
    if m < 1e-6:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / m, y / m, z / m, w / m)


def extract_yaw_pitch_roll(q) -> Tuple[float, float, float]:
    """Extracts yaw (Z), pitch (Y), roll (X) from a quaternion (x,y,z,w)."""
    x, y, z, w = q
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    sp = 2.0 * (w * y - z * x)
    sp = clamp(sp, -1.0, 1.0)
    pitch = math.asin(sp)
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    return yaw, pitch, roll


class OrientationTracker:
    """Tracks calibration state and computes frame-to-frame orientation deltas."""
    def __init__(self):
        self._grv_offset = (0.0, 0.0, 0.0, 1.0)
        self._calibrated = False
        self._have_prev = False
        self._prev_yaw = 0.0
        self._prev_pitch = 0.0
        self._prev_roll = 0.0
        self._zero_roll = 0.0

    @property
    def calibrated(self):
        return self._calibrated

    def reset(self):
        self._calibrated = False
        self._have_prev = False

    def calibrate(self, rv, grv):
        """Computes grv_offset from first packet with both rotation vector and game rotation vector."""
        if rv is not None and grv is not None:
            self._grv_offset = quat_normalize(quat_multiply(rv, quat_inverse(grv)))
            label = "rv*inv(grv) offset"
        elif rv is not None:
            label = "rv only, identity offset"
        else:
            label = "grv only, identity offset"

        self._calibrated = True
        self._have_prev = False
        print(f"motion receiver: calibrated ({label})")

    def update(self, rotation) -> Optional[Tuple[float, float, float, float]]:
        """Applies offset, extracts euler, and computes deltas.

        Returns (d_yaw, d_pitch, d_roll, roll) on a normal frame,
        or None on the first frame after calibration (baseline capture).
        """
        corrected = quat_normalize(quat_multiply(self._grv_offset, rotation))
        yaw, pitch, roll = extract_yaw_pitch_roll(corrected)

        if not self._have_prev:
            self._have_prev = True
            self._prev_yaw = yaw
            self._prev_pitch = pitch
            self._prev_roll = roll
            self._zero_roll = roll
            return None

        d_yaw = angle_delta(yaw, self._prev_yaw)
        d_pitch = angle_delta(pitch, self._prev_pitch)
        d_roll = angle_delta(roll, self._prev_roll)
        self._prev_yaw = yaw
        self._prev_pitch = pitch
        self._prev_roll = roll

        return d_yaw, d_pitch, d_roll, roll

    @property
    def zero_roll(self):
        return self._zero_roll
