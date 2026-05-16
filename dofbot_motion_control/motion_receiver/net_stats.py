import time


class NetStats:
    """Handles sequence tracking, interval timing, and drop counting."""
    def __init__(self):
        self.reset()

    def reset(self):
        self._start_time = time.monotonic()
        self._last_seq = None
        self._last_recv_time = None
        self._recv_packets = 0
        self._dropped_packets = 0
        self._interval_sum = 0.0
        self._interval_count = 0
        self._interval_max = 0.0

    def record(self, seq, recv_time):
        self._recv_packets += 1

        if self._last_recv_time is not None:
            dt = recv_time - self._last_recv_time
            self._interval_sum += dt
            self._interval_count += 1
            if dt > self._interval_max:
                self._interval_max = dt
        self._last_recv_time = recv_time

        if self._last_seq is not None:
            gap = (seq - self._last_seq) & 0xFFFFFFFF
            if gap > 1:
                self._dropped_packets += gap - 1
        self._last_seq = seq

    def print_summary(self, label):
        if self._recv_packets <= 0 and self._dropped_packets <= 0:
            return
        duration_s = max(time.monotonic() - self._start_time, 1e-6)
        hz = self._recv_packets / duration_s
        avg_ms = (self._interval_sum / self._interval_count * 1000.0) if self._interval_count else 0.0
        max_ms = self._interval_max * 1000.0
        print(
            "motion receiver net:",
            label,
            f"hz={hz:.1f}",
            f"avg_dt={avg_ms:.1f}ms",
            f"max_dt={max_ms:.1f}ms",
            f"drops={self._dropped_packets}",
        )
