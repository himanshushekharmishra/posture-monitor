"""End-to-end pure pipeline: fake landmarks -> features -> score -> EMA -> state machine."""
import json
from pathlib import Path

from src.engine.calibration import build_baseline
from src.engine.features import deviation_score, extract_features, measure
from src.engine.state import Ema, PostureStateMachine
from src.schemas.models import PostureState as S
from tests.test_features import make_pose

SETTINGS = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "settings.json").read_text()
)
FPS = SETTINGS["process_fps"]


def simulate(poses_by_second):
    """poses_by_second: list of (seconds, pose or None). Returns states and alert times."""
    upright = make_pose()
    baseline = build_baseline([measure(upright)] * 10, "t")
    ema = Ema(SETTINGS["ema_alpha"])
    m = PostureStateMachine.from_settings(SETTINGS)
    t, alerts, states = 0.0, [], []
    for seconds, pose in poses_by_second:
        for _ in range(int(seconds * FPS)):
            score = None
            if pose is not None:
                f = extract_features(pose, baseline)
                score = ema.update(deviation_score(f, baseline, SETTINGS))
            state, alert = m.update(score, t)
            if state == S.AWAY:
                ema.reset()
            if alert:
                alerts.append(t)
            states.append(state)
            t += 1 / FPS
    return states, alerts


def test_upright_session_never_alerts():
    states, alerts = simulate([(120, make_pose())])
    assert alerts == [] and states[-1] == S.GOOD


def test_head_forward_alerts_after_persist_seconds():
    persist = SETTINGS["persist_seconds"]
    states, alerts = simulate([(10, make_pose()), (persist + 10, make_pose(ear_y=0.42))])
    assert len(alerts) == 1
    # EMA delays the start by under a second; the alert comes after persist_seconds.
    assert persist + 10 <= alerts[0] <= persist + 12
    assert states[-1] == S.ALERTED


def test_brief_glance_down_is_ignored():
    states, alerts = simulate([(10, make_pose()), (5, make_pose(ear_y=0.42)), (60, make_pose())])
    assert alerts == [] and states[-1] == S.GOOD


def test_leaving_desk_goes_away_and_back():
    timeout = SETTINGS["away_timeout_seconds"]
    states, _ = simulate([(5, make_pose()), (timeout + 5, None), (5, make_pose())])
    assert S.AWAY in states and states[-1] == S.GOOD
