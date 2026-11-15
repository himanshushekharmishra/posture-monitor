import math

import pytest

from src.utils.timing import FrameThrottle, LatencyTimer


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_throttle_allows_first_frame_then_blocks():
    clock = FakeClock()
    th = FrameThrottle(5, clock=clock)
    assert th.ready()
    clock.t = 0.1
    assert not th.ready()
    clock.t = 0.2
    assert th.ready()


def test_throttle_rate_over_one_second():
    clock = FakeClock()
    th = FrameThrottle(5, clock=clock)
    passed = 0
    for i in range(1000):  # 1 ms steps
        clock.t = i / 1000
        passed += th.ready()
    assert passed == 5


def test_throttle_no_burst_after_stall():
    clock = FakeClock()
    th = FrameThrottle(5, clock=clock)
    th.ready()
    clock.t = 5.0
    assert th.ready()
    assert not th.ready()


def test_throttle_rejects_bad_fps():
    with pytest.raises(ValueError):
        FrameThrottle(0)


def test_latency_timer_reports_ms():
    clock = FakeClock()
    with LatencyTimer(clock=clock) as t:
        clock.t = 0.042
    assert math.isclose(t.ms, 42.0)


def test_percentile_interpolates():
    from src.utils.timing import percentile

    vals = [10.0, 20.0, 30.0, 40.0]
    assert percentile(vals, 0) == 10
    assert percentile(vals, 100) == 40
    assert math.isclose(percentile(vals, 50), 25)
    assert percentile([7.0], 95) == 7
    with pytest.raises(ValueError):
        percentile([], 50)


def test_latency_stats_from_values():
    from src.utils.timing import LatencyStats

    s = LatencyStats.from_values([1.0, 2.0, 3.0, 4.0, 100.0])
    assert s.count == 5 and s.max == 100 and s.p50 == 3
    assert math.isclose(s.mean, 22.0)
    assert s.p95 > s.p50
