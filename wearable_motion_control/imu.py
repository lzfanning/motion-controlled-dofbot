from machine import Pin, SPI
import math
import time

# ICM-45686 registers
# Datasheet: https://www.mouser.com/catalog/specsheets/TDK_DS_000577_ICM_45686.pdf
_WHO_AM_I = 0x72
_WHO_EXPECTED = 0xE9
_PWR_MGMT0 = 0x10
_INT1_CONFIG0 = 0x16
_INT1_CONFIG1 = 0x17
_INT1_CONFIG2 = 0x18
_INT1_STATUS0 = 0x19
_INT1_STATUS1 = 0x1A
_ACCEL_CONFIG0 = 0x1B
_GYRO_CONFIG0 = 0x1C
_ACCEL_DATA = 0x00

# +/-4g -> 8192 LSB/g
_ACCEL_SENS = 8192.0
# +/-2000dps -> 16.4 LSB/dps
_GYRO_SENS = 16.4

_DEG_TO_RAD = math.pi / 180.0


class IMU:
    """Reads raw gyroscope and accelerometer data and calibrates gyro bias."""
    def __init__(self, cs_pin=16, sck_pin=23, mosi_pin=22, miso_pin=21, int_pin=2):
        self._cs = Pin(cs_pin, Pin.OUT, value=1)
        self._spi = SPI(
            1,
            baudrate=8_000_000,
            polarity=0,
            phase=0,
            sck=Pin(sck_pin),
            mosi=Pin(mosi_pin),
            miso=Pin(miso_pin),
        )
        self._int_pin = Pin(int_pin, Pin.IN, Pin.PULL_DOWN)

        self._bias_x = 0.0
        self._bias_y = 0.0
        self._bias_z = 0.0

        self._data_ready = False
        self._interrupt_enabled = True

        try:
            self._int_pin.irq(trigger=Pin.IRQ_RISING, handler=self._on_data_ready)
        except Exception as e:
            print("INT irq unavailable, polling only:", e)
            self._interrupt_enabled = False

    @property
    def data_ready(self):
        return self._data_ready
    
    @property
    def interrupt_enabled(self):
        return self._interrupt_enabled

    def init(self):
        who = self._read_reg(_WHO_AM_I)[0]
        print("WHO_AM_I:", hex(who))
        if who != _WHO_EXPECTED:
            raise RuntimeError("ICM-45686 not found")

        self._write_reg(_INT1_CONFIG0, 0x00)
        self._write_reg(_INT1_CONFIG1, 0x00)
        self._write_reg(_INT1_CONFIG2, 0x01)

        # Accel range: +/-4g at 100Hz
        self._write_reg(_ACCEL_CONFIG0, 0x39)
        # Gyro range: +/-2000 dps at 100Hz
        self._write_reg(_GYRO_CONFIG0, 0x19)

        # Accel + gyro low-noise mode
        self._write_reg(_PWR_MGMT0, 0x0F)
        time.sleep_ms(100)

        self._read_reg(_INT1_STATUS0)
        self._read_reg(_INT1_STATUS1)
        self._write_reg(_INT1_CONFIG0, 0x04)

        print("INT1 cfg:", hex(self._read_reg(_INT1_CONFIG0)[0]),
              hex(self._read_reg(_INT1_CONFIG2)[0]))
        print("ACCEL/GYRO cfg:", hex(self._read_reg(_ACCEL_CONFIG0)[0]),
              hex(self._read_reg(_GYRO_CONFIG0)[0]))

    def calibrate(self, good_samples_target=100, max_attempts=600) -> tuple[float, float, float] | None:
        print("calibrating gyro bias...")

        sx = sy = sz = 0.0
        sax = say = saz = 0.0
        good_count = 0

        for _ in range(max_attempts):
            m = self._read_reg(_ACCEL_DATA, 12)

            ax_raw = self._decode_i16_le(m[0], m[1])
            ay_raw = self._decode_i16_le(m[2], m[3])
            az_raw = self._decode_i16_le(m[4], m[5])

            gx_raw = self._decode_i16_le(m[6], m[7])
            gy_raw = self._decode_i16_le(m[8], m[9])
            gz_raw = self._decode_i16_le(m[10], m[11])

            ax_g = ax_raw / _ACCEL_SENS
            ay_g = ay_raw / _ACCEL_SENS
            az_g = az_raw / _ACCEL_SENS

            gx_dps = gx_raw / _GYRO_SENS
            gy_dps = gy_raw / _GYRO_SENS
            gz_dps = gz_raw / _GYRO_SENS

            acc_mag = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
            gyro_mag = math.sqrt(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps)

            accel_ok = abs(acc_mag - 1.0) < 0.10
            gyro_ok = gyro_mag < 5.0

            if accel_ok and gyro_ok:
                sx += gx_raw
                sy += gy_raw
                sz += gz_raw

                sax += ax_raw
                say += ay_raw
                saz += az_raw

                good_count += 1

                if good_count >= good_samples_target:
                    break

            time.sleep_ms(10)

        if good_count < 20:
            print("calibration skipped: not enough stable samples")
            print("keeping previous gyro bias:", self._bias_x, self._bias_y, self._bias_z)
            return None

        self._bias_x = sx / good_count
        self._bias_y = sy / good_count
        self._bias_z = sz / good_count

        avg_ax = sax / good_count / _ACCEL_SENS
        avg_ay = say / good_count / _ACCEL_SENS
        avg_az = saz / good_count / _ACCEL_SENS

        print("gyro bias:", self._bias_x, self._bias_y, self._bias_z)
        print("calibration samples:", good_count, "/", max_attempts)

        return (avg_ax, avg_ay, avg_az)

    def read_motion(self) -> tuple[float, float, float, float, float, float]:
        m = self._read_reg(_ACCEL_DATA, 12)

        ax_raw = self._decode_i16_le(m[0], m[1])
        ay_raw = self._decode_i16_le(m[2], m[3])
        az_raw = self._decode_i16_le(m[4], m[5])

        gx_raw = self._decode_i16_le(m[6], m[7]) - self._bias_x
        gy_raw = self._decode_i16_le(m[8], m[9]) - self._bias_y
        gz_raw = self._decode_i16_le(m[10], m[11]) - self._bias_z

        ax_g = ax_raw / _ACCEL_SENS
        ay_g = ay_raw / _ACCEL_SENS
        az_g = az_raw / _ACCEL_SENS

        gx = gx_raw / _GYRO_SENS * _DEG_TO_RAD
        gy = gy_raw / _GYRO_SENS * _DEG_TO_RAD
        gz = gz_raw / _GYRO_SENS * _DEG_TO_RAD

        return gx, gy, gz, ax_g, ay_g, az_g

    def clear_data_ready(self):
        self._data_ready = False

    def _on_data_ready(self, pin):
        self._data_ready = True

    def _read_reg(self, reg, n=1):
        self._cs(0)
        self._spi.write(bytes([reg | 0x80]))
        data = self._spi.read(n)
        self._cs(1)
        return data

    def _write_reg(self, reg, value):
        self._cs(0)
        self._spi.write(bytes([reg & 0x7F, value]))
        self._cs(1)

    @staticmethod
    def _decode_i16_le(low_byte, high_byte):
        v = (high_byte << 8) | low_byte
        return v - 65536 if v & 0x8000 else v
