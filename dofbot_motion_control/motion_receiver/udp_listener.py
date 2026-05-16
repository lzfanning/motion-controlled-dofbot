import socket
import struct
import time

from protocol import PACKET_FORMAT, UDP_PORT

_PACKET_SIZE = struct.calcsize(PACKET_FORMAT)


class UDPListener:
    """Receives and yields UDP motion/control packets."""
    def __init__(self, ip="0.0.0.0", port=UDP_PORT):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((ip, port))
        self._sock.setblocking(False)
        print(f"motion receiver: listening on {ip}:{port}")

    def receive(self):
        """Drains the socket and yields each received item.

        Yields either:
          ("cmd", command_bytes, recv_time)
          ("motion", (seq, rv, grv), recv_time)
        """
        while True:
            try:
                packet, _ = self._sock.recvfrom(256)
            except BlockingIOError:
                break
            except OSError:
                break

            recv_time = time.monotonic()

            if len(packet) == 4:
                yield ("cmd", packet[:3], recv_time)
            elif len(packet) == _PACKET_SIZE:
                yield ("motion", self._decode_packet(packet), recv_time)

    @staticmethod
    def _decode_packet(packet):
        """Decodes a motion packet into (seq, rv_quat, grv_quat).

        rv_quat / grv_quat are (x,y,z,w) tuples, or None if timestamp is 0.
        """
        data = struct.unpack(PACKET_FORMAT, packet)
        seq = data[0]
        ts_rv_ns = data[13]
        rv = (data[14], data[15], data[16], data[17]) if ts_rv_ns > 0 else None
        ts_grv_ns = data[18]
        grv = (data[19], data[20], data[21], data[22]) if ts_grv_ns > 0 else None
        return seq, rv, grv
