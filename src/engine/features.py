"""Landmarks -> PostureFeatures.  Phase 2.  Pure logic, no I/O."""
from __future__ import annotations

import math

from src.schemas.models import Baseline, Point, PostureFeatures, PostureSample
from src.utils.geometry import distance, line_angle_deg, midpoint

NOSE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER = 0, 7, 8, 11, 12
KEY_LANDMARKS = (L_EAR, R_EAR, L_SHOULDER, R_SHOULDER)


def level_angle_deg(a: Point, b: Point) -> float:
    """Angle of the a-b line from horizontal in degrees (-90..90).

    The points are ordered left-to-right by x first, so the result doesn't depend
    on which side is "left" or on whether the image is mirrored.
    """
    left, right = (a, b) if a.x <= b.x else (b, a)
    return line_angle_deg(left, right)


def measure(landmarks: list[Point]) -> PostureSample:
    """Raw measurements from one frame of 33 pose landmarks."""
    if len(landmarks) <= max(KEY_LANDMARKS):
        raise ValueError(f"expected 33 landmarks, got {len(landmarks)}")
    l_ear, r_ear = landmarks[L_EAR], landmarks[R_EAR]
    l_sh, r_sh = landmarks[L_SHOULDER], landmarks[R_SHOULDER]
    width = distance(l_sh, r_sh)
    if width <= 0:
        raise ValueError("shoulder width is zero")
    ear_mid, sh_mid = midpoint(l_ear, r_ear), midpoint(l_sh, r_sh)
    return PostureSample(
        neck_ratio=(sh_mid.y - ear_mid.y) / width,
        shoulder_width=width,
        shoulder_tilt=level_angle_deg(l_sh, r_sh),
        head_tilt=level_angle_deg(l_ear, r_ear),
        visibility=min(landmarks[i].visibility for i in KEY_LANDMARKS),
    )


def extract_features(landmarks: list[Point], baseline: Baseline | None) -> PostureFeatures:
    """Features for one frame. lean_ratio is 1.0 when there is no baseline yet."""
    s = measure(landmarks)
    lean = s.shoulder_width / baseline.shoulder_width if baseline else 1.0
    return PostureFeatures(
        neck_ratio=s.neck_ratio,
        lean_ratio=lean,
        shoulder_tilt=s.shoulder_tilt,
        head_tilt=s.head_tilt,
        visibility=s.visibility,
    )


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def deviation_components(
    f: PostureFeatures, baseline: Baseline, settings: dict
) -> dict[str, float]:
    """Each component is 0 (matches baseline) .. 1 (far off)."""
    tilt_norm = float(settings["tilt_norm_degrees"])
    neck_drop = (
        (baseline.neck_ratio - f.neck_ratio) / baseline.neck_ratio
        if baseline.neck_ratio > 0
        else 0.0
    )
    return {
        # Only penalise the head dropping / moving forward, not sitting taller.
        "neck": _clamp01(neck_drop),
        # Only penalise leaning in toward the screen, not leaning back.
        "lean": _clamp01(f.lean_ratio - 1.0),
        "shoulder_tilt": _clamp01(abs(f.shoulder_tilt - baseline.shoulder_tilt) / tilt_norm),
        "head_tilt": _clamp01(abs(f.head_tilt - baseline.head_tilt) / tilt_norm),
    }


def deviation_score(f: PostureFeatures, baseline: Baseline, settings: dict) -> float:
    """Weighted deviation from baseline. 0 = baseline posture."""
    weights: dict[str, float] = settings["weights"]
    parts = deviation_components(f, baseline, settings)
    score = sum(weights[k] * v for k, v in parts.items())
    return 0.0 if math.isnan(score) else score
