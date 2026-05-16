import json
import os

from typing import Optional
from animation import Animation

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "animations.json")
_SMOOTH_WINDOW = 5


class AnimationStore:
    """Manages an ordered list of recorded animations persisted with a JSON file."""
    def __init__(self, path=_DEFAULT_PATH):
        self._path = path
        self._animations = []
        self._index = -1 # -1 = no animation selected (home)

    def load(self):
        if not os.path.exists(self._path):
            self._animations = []
            return

        with open(self._path, "r") as f:
            data = json.load(f)

        self._animations = [Animation.from_dict(d) for d in data]
        print(f"animation store: loaded {len(self._animations)} animations from {self._path}")

    def save(self):
        data = [a.to_dict() for a in self._animations]

        with open(self._path, "w") as f:
            json.dump(data, f)

        print(f"animation store: saved {len(self._animations)} animations to {self._path}")

    def add(self, animation: Animation):
        """Smooths and appends a new animation, then saves."""
        smoothed_anim = animation.smooth(window=_SMOOTH_WINDOW)
        self._animations.append(smoothed_anim)
        self.save()
        print(f"animation store: added animation "
              f"({len(smoothed_anim)} frames, {smoothed_anim.duration_s:.1f}s)")

    @property
    def count(self):
        return len(self._animations)

    @property
    def index(self):
        return self._index

    def delete_current(self) -> Optional[Animation]:
        """Removes the currently selected animation. Returns the next one or None."""
        if self._index < 0 or self._index >= len(self._animations):
            return None

        removed = self._animations.pop(self._index)
        self.save()
        print(f"animation store: deleted animation ({len(removed)} frames)")

        if not self._animations:
            self._index = -1
            return None

        # Stay at same index, wrap if needed
        self._index = self._index % len(self._animations)
        return self._animations[self._index]

    def next(self) -> Optional[Animation]:
        """Goes to the next animation, wrapping around. Returns it or None."""
        if not self._animations:
            return None

        self._index = (self._index + 1) % len(self._animations)

        return self._animations[self._index]

    def prev(self) -> Optional[Animation]:
        """Goes to the previous animation, wrapping around. Returns it or None."""
        if not self._animations:
            return None

        if self._index <= 0:
            self._index = len(self._animations) - 1
        else:
            self._index -= 1

        return self._animations[self._index]

    def current(self) -> Optional[Animation]:
        """Returns the currently selected animation, or None."""
        if self._index < 0 or self._index >= len(self._animations):
            return None
        return self._animations[self._index]
