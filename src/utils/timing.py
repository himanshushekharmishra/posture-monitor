"""Frame throttling and latency measurement.  Phase 1."""


class FrameThrottle:
    """Lets a frame through at most `fps` times per second."""

    def __init__(self, fps: float) -> None:
        raise NotImplementedError


class LatencyTimer:
    """Context manager that records elapsed ms per frame."""
