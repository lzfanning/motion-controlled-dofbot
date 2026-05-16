class Animation:
    """Represents a recorded sequence of timed servo poses."""
    def __init__(self, frames=None):
        self._frames = frames or []

    def add_frame(self, dt_ms, joints):
        """Records a frame: delta time in ms and 6 joint values."""
        self._frames.append((dt_ms, list(joints)))

    def __len__(self):
        return len(self._frames)

    @property
    def frames(self):
        return tuple(self._frames)

    @property
    def duration_s(self):
        """Returns the total animation duration in seconds."""
        return sum(dt_ms for dt_ms, _ in self._frames) / 1000.0

    def to_dict(self):
        return {"frames": self._frames}

    @classmethod
    def from_dict(cls, d):
        return cls(frames=[tuple(f) for f in d["frames"]])

    def smooth(self, window=5) -> "Animation":
        """Returns a new Animation with joint positions smoothed.

        Uses a forward-backward moving average (zero phase lag).
        The window size is clamped to the number of frames.
        """
        n = len(self._frames)
        if n < 2:
            return Animation(frames=list(self._frames))

        window = min(window, n)
        half_window = window // 2
        num_joints = len(self._frames[0][1])

        # Extract joint channels
        channels = []
        for j in range(num_joints):
            channels.append([joints[j] for _, joints in self._frames])

        # Forward-backward moving average per channel
        smoothed_channels = []
        for ch in channels:
            forward = self._apply_moving_average(ch, half_window)
            backward = self._apply_moving_average(forward[::-1], half_window)[::-1]
            smoothed_channels.append(backward)

        # Put frames back together, keeping original timing
        smoothed_frames = []
        for i in range(n):
            dt_ms = self._frames[i][0]
            joints = [smoothed_channels[j][i] for j in range(num_joints)]
            smoothed_frames.append((dt_ms, joints))

        return Animation(frames=smoothed_frames)

    def _apply_moving_average(self, values, half_window):
        """Applies a running average over a fixed-size window."""
        n = len(values)
        out = [0.0] * n
        running = 0.0
        count = 0

        for i in range(n):
            running += values[i]
            count += 1

            # Shrink window: drop the element that fell off the left edge
            if i > 2 * half_window:
                running -= values[i - 2 * half_window - 1]
                count -= 1

            out[i] = running / count

        return out
