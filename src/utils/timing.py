"""Frame throttling and latency measurement.  Phase 1."""
from __future__ import annotations

import time
from dataclasses import dataclass
from types import TracebackType
from typing import Callable

Clock = Callable[[], float]


class FrameThrottle:
    """Lets a frame through at most `fps` times per second."""

    def __init__(self, fps: float, clock: Clock = time.monotonic) -> None:
        if fps <= 0:
            raise ValueError("fps must be > 0")
        self.interval = 1.0 / fps
        self._clock = clock
        self._next: float | None = None

    def ready(self) -> bool:
        """True if a frame may be processed now (and claims that slot)."""
        now = self._clock()
        if self._next is None or now >= self._next:
            # Keep the ideal cadence, but after a stall restart from now instead of
            # catching up with a burst of frames.
            late = self._next is None or now - self._next >= self.interval
            base = now if late else self._next
            self._next = base + self.interval
            return True
        return False

    def seconds_until_ready(self) -> float:
        if self._next is None:
            return 0.0
        return max(0.0, self._next - self._clock())

    def wait(self) -> None:
        """Sleep until the next slot is open, then claim it."""
        delay = self.seconds_until_ready()
        if delay > 0:
            time.sleep(delay)
        while not self.ready():
            time.sleep(0.001)


class LatencyTimer:
    """Context manager that records elapsed ms per frame."""

    def __init__(self, clock: Clock = time.perf_counter) -> None:
        self._clock = clock
        self._start = 0.0
        self.ms = 0.0

    def __enter__(self) -> LatencyTimer:
        self._start = self._clock()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.ms = (self._clock() - self._start) * 1000.0


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..100) of a non-empty list."""
    if not values:
        raise ValueError("no values")
    if not 0 <= pct <= 100:
        raise ValueError("pct must be in 0..100")
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass(frozen=True)
class LatencyStats:
    count: int
    mean: float
    p50: float
    p95: float
    max: float

    @classmethod
    def from_values(cls, values: list[float]) -> LatencyStats:
        return cls(
            count=len(values),
            mean=sum(values) / len(values),
            p50=percentile(values, 50),
            p95=percentile(values, 95),
            max=max(values),
        )
