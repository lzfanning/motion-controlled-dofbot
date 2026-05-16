import math
import time

from imu import IMU

_COS_45 = math.cos(math.pi / 4)
_PRE_ROTATION = (_COS_45, _COS_45, 0, 0)
_SWIZZLE = (2, 1, 3)
_SIGNS = (1, -1, 1)

class MahonyFilter:
    """Turns gyro/accel data into a useful quaternion."""
    def __init__(self, kp=0.5, ki=0.02):
        self._kp = kp
        self._ki = ki

        self._qw = 1.0
        self._qx = 0.0
        self._qy = 0.0
        self._qz = 0.0

        self._ix = 0.0
        self._iy = 0.0
        self._iz = 0.0

        self._prev = [1.0, 0.0, 0.0, 0.0]

    @property
    def remapped_quaternion(self) -> tuple[float, float, float, float]:
        """Returns quaternion remapped to match what the receiver expects."""
        return self._remap_quaternion(self._qw, self._qx, self._qy, self._qz, _PRE_ROTATION, _SWIZZLE, _SIGNS, self._prev)

    def reset_from_accel(self, ax, ay, az):
        roll = math.atan2(ay, az)
        pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))
        self._set_from_euler(roll, pitch, 0.0)
        self._ix = 0.0
        self._iy = 0.0
        self._iz = 0.0

    def settle(self, imu: IMU, num_samples=20):
        last_ms = time.ticks_ms()
        print("settling Mahony filter...")
        for _ in range(num_samples):
            now = time.ticks_ms()
            dt = time.ticks_diff(now, last_ms) / 1000.0
            last_ms = now
            if dt <= 0 or dt > 0.1:
                dt = 0.01
            gx, gy, gz, ax, ay, az = imu.read_motion()
            self.update(gx, gy, gz, ax, ay, az, dt)
            time.sleep_ms(10)
        print("settled")

    def update(self, gx, gy, gz, ax, ay, az, dt):
        norm = math.sqrt(ax * ax + ay * ay + az * az)

        if norm > 0.000001:
            ax /= norm
            ay /= norm
            az /= norm

            qw = self._qw
            qx = self._qx
            qy = self._qy
            qz = self._qz

            vx = 2.0 * (qx * qz - qw * qy)
            vy = 2.0 * (qw * qx + qy * qz)
            vz = qw * qw - qx * qx - qy * qy + qz * qz

            ex = ay * vz - az * vy
            ey = az * vx - ax * vz
            ez = ax * vy - ay * vx

            self._ix += self._ki * ex * dt
            self._iy += self._ki * ey * dt
            self._iz += self._ki * ez * dt

            gx += self._kp * ex + self._ix
            gy += self._kp * ey + self._iy
            gz += self._kp * ez + self._iz

        qw = self._qw
        qx = self._qx
        qy = self._qy
        qz = self._qz

        halfdt = 0.5 * dt

        dqw = (-qx * gx - qy * gy - qz * gz) * halfdt
        dqx = ( qw * gx + qy * gz - qz * gy) * halfdt
        dqy = ( qw * gy - qx * gz + qz * gx) * halfdt
        dqz = ( qw * gz + qx * gy - qy * gx) * halfdt

        qw += dqw
        qx += dqx
        qy += dqy
        qz += dqz

        norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
        if norm > 0:
            self._qw = qw / norm
            self._qx = qx / norm
            self._qy = qy / norm
            self._qz = qz / norm
    
    def _remap_quaternion(self, qw, qx, qy, qz, pre_rot, swizzle, signs, prev) -> tuple[float, float, float, float]:
        rw, rx, ry, rz = pre_rot
        pw = qw*rw - qx*rx - qy*ry - qz*rz
        px = qw*rx + qx*rw + qy*rz - qz*ry
        py = qw*ry - qx*rz + qy*rw + qz*rx
        pz = qw*rz + qx*ry - qy*rx + qz*rw

        comps = (pw, px, py, pz)
        ow = comps[0]
        ox = comps[swizzle[0]] * signs[0]
        oy = comps[swizzle[1]] * signs[1]
        oz = comps[swizzle[2]] * signs[2]

        dot = ow*prev[0] + ox*prev[1] + oy*prev[2] + oz*prev[3]
        if dot < 0:
            ow, ox, oy, oz = -ow, -ox, -oy, -oz
        prev[0], prev[1], prev[2], prev[3] = ow, ox, oy, oz

        return ow, ox, oy, oz

    def _set_from_euler(self, roll, pitch, yaw):
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)

        self._qw = cr * cp * cy + sr * sp * sy
        self._qx = sr * cp * cy - cr * sp * sy
        self._qy = cr * sp * cy + sr * cp * sy
        self._qz = cr * cp * sy - sr * sp * cy
