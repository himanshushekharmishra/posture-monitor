import json
import math
from pathlib import Path

import pytest

from src.engine.calibration import baseline_from_dict, baseline_to_dict, build_baseline
from src.engine.features import (
    L_EAR, L_SHOULDER, R_EAR, R_SHOULDER, deviation_score, extract_features, measure,
)
from src.schemas.models import Point

SETTINGS = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "settings.json").read_text()
)


def make_pose(
    ear_y: float = 0.30,
    shoulder_y: float = 0.50,
    shoulder_half: float = 0.15,
    ear_half: float = 0.05,
    right_shoulder_dy: float = 0.0,
    vis: float = 0.9,
) -> list[Point]:
    """33 fake landmarks; person faces the camera, so their left is image right."""
    pts = [Point(0.5, 0.5, vis) for _ in range(33)]
    pts[L_EAR] = Point(0.5 + ear_half, ear_y, vis)
    pts[R_EAR] = Point(0.5 - ear_half, ear_y, vis)
    pts[L_SHOULDER] = Point(0.5 + shoulder_half, shoulder_y, vis)
    pts[R_SHOULDER] = Point(0.5 - shoulder_half, shoulder_y + right_shoulder_dy, vis)
    return pts


def baseline_for(pose: list[Point]):
    return build_baseline([measure(pose)] * 5, "2026-01-01T00:00:00+00:00")


def test_measure_upright():
    s = measure(make_pose())
    assert math.isclose(s.shoulder_width, 0.30)
    assert math.isclose(s.neck_ratio, 0.20 / 0.30)
    assert math.isclose(s.shoulder_tilt, 0, abs_tol=1e-9)
    assert math.isclose(s.head_tilt, 0, abs_tol=1e-9)
    assert math.isclose(s.visibility, 0.9)


def test_tilt_is_independent_of_left_right_order():
    pose = make_pose(right_shoulder_dy=0.05)
    mirrored = [Point(1 - p.x, p.y, p.visibility) for p in pose]
    a, b = measure(pose).shoulder_tilt, measure(mirrored).shoulder_tilt
    assert abs(a) < 90 and math.isclose(abs(a), abs(b))
    assert abs(a) > 5


def test_lean_ratio_defaults_to_one_without_baseline():
    assert extract_features(make_pose(), None).lean_ratio == 1.0


def test_upright_pose_scores_near_zero():
    pose = make_pose()
    f = extract_features(pose, baseline_for(pose))
    assert deviation_score(f, baseline_for(pose), SETTINGS) == pytest.approx(0, abs=1e-9)


def test_head_forward_increases_score():
    base = baseline_for(make_pose())
    forward = extract_features(make_pose(ear_y=0.40), base)
    score = deviation_score(forward, base, SETTINGS)
    assert score >= SETTINGS["slouch_threshold"]


def test_leaning_in_increases_score_but_sitting_taller_does_not():
    base = baseline_for(make_pose())
    lean_in = extract_features(make_pose(shoulder_half=0.20, ear_half=0.07), base)
    taller = extract_features(make_pose(ear_y=0.25), base)
    assert deviation_score(lean_in, base, SETTINGS) > 0.05
    assert deviation_score(taller, base, SETTINGS) == pytest.approx(0, abs=1e-9)


def test_score_is_bounded_by_weight_sum():
    base = baseline_for(make_pose())
    awful = extract_features(
        make_pose(ear_y=0.55, shoulder_half=0.40, right_shoulder_dy=0.3), base
    )
    assert deviation_score(awful, base, SETTINGS) <= sum(SETTINGS["weights"].values()) + 1e-9


def test_measure_rejects_short_landmark_list():
    with pytest.raises(ValueError):
        measure([Point(0, 0)] * 5)


def test_baseline_uses_median_and_round_trips():
    good = [measure(make_pose()) for _ in range(4)]
    outlier = measure(make_pose(ear_y=0.10))
    b = build_baseline([*good, outlier], "t")
    assert math.isclose(b.neck_ratio, good[0].neck_ratio)
    assert baseline_from_dict(json.loads(json.dumps(baseline_to_dict(b)))) == b


def test_build_baseline_rejects_empty():
    with pytest.raises(ValueError):
        build_baseline([], "t")


def test_bad_baselines_are_rejected():
    from src.engine.calibration import baseline_from_dict

    good = {"neck_ratio": 0.6, "shoulder_width": 0.3, "shoulder_tilt": 0, "head_tilt": 0,
            "recorded_at": "t"}
    assert baseline_from_dict(good).shoulder_width == 0.3
    for bad in ({"shoulder_width": 0}, {"neck_ratio": -0.1}, {"neck_ratio": float("nan")},
                {"head_tilt": 120}):
        with pytest.raises(ValueError):
            baseline_from_dict({**good, **bad})


def test_calibration_with_head_below_shoulders_fails():
    upside_down = measure(make_pose(ear_y=0.6, shoulder_y=0.5))
    with pytest.raises(ValueError, match="ears"):
        build_baseline([upside_down] * 10, "t")


def test_unreadable_baseline_file_is_ignored(tmp_path):
    from src.tools.baseline_store import load_baseline

    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({"neck_ratio": 0.6, "shoulder_width": 0, "shoulder_tilt": 0,
                             "head_tilt": 0, "recorded_at": "t"}))
    assert load_baseline(p) is None
    p.write_text("{oops")
    assert load_baseline(p) is None
