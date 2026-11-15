from src.engine.state import PostureStateMachine
from src.schemas.models import MonitorStatus, PostureState
from src.tools.tray import make_icon_image, status_text
from src.workflows.monitor_loop import MonitorControl


def test_publish_only_notifies_on_change():
    seen = []
    c = MonitorControl(on_status=seen.append)
    c.publish(state=PostureState.GOOD)
    c.publish(state=PostureState.GOOD)
    c.publish(alerts_today=1)
    assert [s.state for s in seen] == [PostureState.GOOD, PostureState.GOOD]
    assert seen[-1].alerts_today == 1


def test_pause_and_recalibrate_flags():
    c = MonitorControl()
    c.toggle_pause()
    assert c.paused
    c.toggle_pause()
    assert not c.paused
    c.request_recalibrate()
    assert c.recalibrate_pending and c.take_recalibrate()
    assert not c.take_recalibrate()
    c.stop()
    assert c.stopped


def test_reset_goes_away_but_keeps_cooldown():
    m = PostureStateMachine(0.25, persist_seconds=1, cooldown_seconds=100, away_timeout=10)
    m.update(0.0, 0)
    for i in range(10):
        m.update(0.9, i * 0.2)
    assert m.state == PostureState.ALERTED
    m.reset()
    assert m.state == PostureState.AWAY
    alerts = [m.update(0.9, 3 + i * 0.2)[1] for i in range(20)]
    assert not any(alerts)  # still inside the cooldown after the reset


def test_status_text_and_icons():
    assert status_text(MonitorStatus(PostureState.GOOD, alerts_today=1)) == "Good - 1 alert today"
    assert status_text(MonitorStatus(paused=True, alerts_today=3)).startswith("Paused")
    assert status_text(MonitorStatus(note="camera unavailable")).startswith("Camera unavailable")
    img = make_icon_image(PostureState.ALERTED, False)
    assert img.size == (64, 64)
    assert make_icon_image(PostureState.GOOD, True) is make_icon_image(PostureState.GOOD, True)


def test_failing_status_listener_does_not_stop_monitoring():
    def broken(status):
        raise RuntimeError("tray not ready")

    c = MonitorControl(on_status=broken)
    c.publish(state=PostureState.GOOD)  # must not raise
    assert c.status.state == PostureState.GOOD


def test_recalibrate_with_busy_camera_keeps_running(monkeypatch):
    from src.workflows import monitor_loop

    def camera_busy(*args, **kwargs):
        raise RuntimeError("Could not open camera index 0")

    sent = []
    monkeypatch.setattr(monitor_loop.calibrate_flow, "run", camera_busy)
    monkeypatch.setattr(monitor_loop, "notify", lambda title, msg: sent.append(msg))
    assert monitor_loop._recalibrate({}, None, tray=True) is None
    assert sent and "camera" in sent[0]


def test_single_instance():
    import subprocess
    import sys

    from src.tools import single_instance

    name = "PostureMonitorTest-single-instance"
    assert single_instance.acquire(name)
    if sys.platform == "win32":
        # A second process must see the first one's lock.
        code = ("from src.tools import single_instance as s; "
                f"print(s.acquire({name!r}))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=str(__import__('pathlib').Path(__file__).parent.parent))
        assert out.stdout.strip() == "False", out.stderr
