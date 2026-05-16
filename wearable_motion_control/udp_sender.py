import socket
import struct
import time

from protocol import PACKET_FORMAT

_PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
_G_TO_MS2 = 9.80665


class UDPSender:
    """Sends command and motion data."""
    def __init__(self, host, port):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._dest = (host, port)
        self._buf = bytearray(_PACKET_SIZE)
        self._seq = 0

    def send_command(self, cmd):
        self._sock.sendto(cmd + b"\x00", self._dest)

    def send_motion(self, gx, gy, gz, ax_g, ay_g, az_g, qw, qx, qy, qz):
        self._seq += 1
        ts_ns = time.ticks_ms() * 1_000_000

        # Convert to SI units that the receiver expects
        ax = ax_g * _G_TO_MS2
        ay = ay_g * _G_TO_MS2
        az = az_g * _G_TO_MS2

        struct.pack_into(
            PACKET_FORMAT,
            self._buf,
            0,
            self._seq,
            ts_ns, ts_ns, 0,
            gx, gy, gz,
            ax, ay, az,
            0.0, 0.0, 0.0,
            ts_ns, qx, qy, qz, qw,
            ts_ns, qx, qy, qz, qw,
            -1.0,
        )

        self._sock.sendto(self._buf, self._dest)
