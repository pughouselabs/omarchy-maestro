"""Gesture and wheel state machines, independent of hardware and desktop."""


class Gesture:
    def __init__(self, threshold=50):
        self.threshold = threshold
        self.active = False
        self.dx = self.dy = 0
        self.direction = None

    def begin(self):
        self.active = True
        self.dx = self.dy = 0
        self.direction = None

    def move(self, dx, dy):
        if not self.active or self.direction is not None:
            return
        self.dx += dx
        self.dy += dy
        if max(abs(self.dx), abs(self.dy)) >= self.threshold:
            if abs(self.dx) > abs(self.dy):
                self.direction = "right" if self.dx > 0 else "left"
            else:
                self.direction = "down" if self.dy > 0 else "up"

    def end(self):
        if not self.active:
            return None
        self.active = False
        return self.direction or "tap"


class WheelAccumulator:
    def __init__(self, step=120):
        if step < 1:
            raise ValueError("step must be positive")
        self.step = step
        self.remainder = 0

    def feed(self, delta, start=False):
        if start:
            self.remainder = 0
        self.remainder += delta
        # Truncate toward zero so opposite movements cancel without false steps.
        count = abs(self.remainder) // self.step
        if self.remainder < 0:
            count = -count
        self.remainder -= count * self.step
        # Bound action bursts from a malformed device packet.
        return max(-32, min(32, count))
