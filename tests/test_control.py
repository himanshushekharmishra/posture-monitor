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
