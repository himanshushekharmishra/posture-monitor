import json
from pathlib import Path

import pytest

from src.engine.state import Ema, PostureStateMachine
from src.schemas.models import PostureState as S
from src.tools.notifier import AlertNotifier

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
BAD, OK, FPS = 0.6, 0.0, 5


def make_machine() -> PostureStateMachine:
    return PostureStateMachine(
        threshold=0.25, persist_seconds=30, cooldown_seconds=420,
        away_timeout=10, recovery_margin=0.05,
    )


def feed(m: PostureStateMachine, score, start: float, seconds: float):
    """Feed a constant score at FPS; return (last_state, alert_times, events)."""
    alerts, events, state = [], [], m.state
    for i in range(int(seconds * FPS)):
        t = start + i / FPS
        state, alert = m.update(score, t)
        if alert:
            alerts.append(t)
        if m.event:
            events.append(m.event)
    return state, alerts, events


def test_ema_smooths_and_resets():
    e = Ema(0.5)
    assert e.update(1.0) == 1.0
    assert e.update(0.0) == 0.5
    e.reset()
    assert e.update(0.2) == 0.2
    with pytest.raises(ValueError):
        Ema(0)


def test_starts_away_then_good_when_person_appears():
    m = make_machine()
    assert m.state == S.AWAY
    state, _, events = feed(m, OK, 0, 1)
    assert state == S.GOOD and events == ["returned"]


def test_short_slouch_does_not_alert():
    m = make_machine()
    feed(m, OK, 0, 1)
    state, alerts, _ = feed(m, BAD, 1, 20)
    assert state == S.SLOUCHING and alerts == []
    state, alerts, events = feed(m, OK, 21, 1)
    assert state == S.GOOD and alerts == [] and events == ["recovered"]


def test_sustained_slouch_alerts_once_then_cooldown():
    m = make_machine()
    feed(m, OK, 0, 1)
    state, alerts, _ = feed(m, BAD, 1, 120)
    assert state == S.ALERTED and alerts == [pytest.approx(31)]
    # Recover, then slouch again inside the 7-minute cooldown: no second alert yet.
    feed(m, OK, 121, 5)
    _, alerts, _ = feed(m, BAD, 126, 330)  # runs past the cooldown end at 451 s
    assert alerts == [pytest.approx(31 + 420)]


def test_still_slouching_after_cooldown_alerts_again():
    m = make_machine()
    feed(m, OK, 0, 1)
    _, alerts, _ = feed(m, BAD, 1, 31 + 420 + 1)
    assert alerts == [pytest.approx(31), pytest.approx(451)]


def test_hysteresis_keeps_slouching_near_threshold():
    m = make_machine()
    feed(m, OK, 0, 1)
    feed(m, BAD, 1, 5)
    state, _, _ = feed(m, 0.22, 6, 5)  # below threshold but above threshold - margin
    assert state == S.SLOUCHING
    state, _, _ = feed(m, 0.19, 11, 1)
    assert state == S.GOOD


def test_no_person_goes_away():
    m = make_machine()
    feed(m, OK, 0, 1)
    state, _, _ = feed(m, None, 1, 5)
    assert state == S.GOOD  # short gap keeps the state
    state, _, events = feed(m, None, 6, 10)
    assert state == S.AWAY and events == ["away"]


def test_away_resets_slouch_timer():
    m = make_machine()
    feed(m, OK, 0, 1)
    feed(m, BAD, 1, 25)
    feed(m, None, 26, 15)
    _, alerts, _ = feed(m, BAD, 41, 10)  # only 10 s of new slouching
    assert alerts == []


def test_from_settings_reads_config():
    m = PostureStateMachine.from_settings(SETTINGS)
    assert m.cooldown_seconds == SETTINGS["cooldown_minutes"] * 60
    assert m.threshold == SETTINGS["slouch_threshold"]


def test_notifier_cycles_variants():
    n = AlertNotifier(ROOT / SETTINGS["alerts_path"], 5)
    msgs = [n.next_message() for _ in range(len(n.variants) + 1)]
    assert msgs[0] == msgs[-1] and len(set(msgs)) == len(n.variants)
