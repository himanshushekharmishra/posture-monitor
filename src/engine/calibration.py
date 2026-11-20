"""Average features over N seconds into a Baseline.  Phase 2.  Pure logic."""
from __future__ import annotations

import math
from dataclasses import asdict
from statistics import median

from src.schemas.models import Baseline, PostureSample


def check_baseline(b: Baseline) -> Baseline:
    """Raise ValueError unless the baseline can be scored against.

    A zero shoulder width would divide by zero in lean_ratio; a non-positive neck
    ratio means the ears were at or below the shoulders, which isn't an upright pose
    (or the file was edited). Tilts come from level_angle_deg, so they're within 90°.
    """
    values = (b.neck_ratio, b.shoulder_width, b.shoulder_tilt, b.head_tilt)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("baseline values must be finite numbers")
    if b.shoulder_width <= 0:
        raise ValueError("baseline shoulder width must be positive")
    if b.neck_ratio <= 0:
        raise ValueError("baseline has the ears at or below the shoulders; sit upright and "
                         "make sure your head and shoulders are in view")
    if abs(b.shoulder_tilt) > 90 or abs(b.head_tilt) > 90:
        raise ValueError("baseline tilt must be within 90 degrees")
    return b


def tilt_warning(b: Baseline, max_tilt_degrees: float) -> str:
    """A hint to recalibrate when the baseline is tilted, or "" if it's level enough.

    Tilt is scored against the baseline, so a crooked baseline makes sitting straight
    later look like a deviation. Only a warning, not an error: with the camera off to
    one side, a tilted baseline can be right for that desk.
    """
    tilted = [f"{name} {abs(v):.0f} degrees"
              for name, v in (("shoulders", b.shoulder_tilt), ("head", b.head_tilt))
              if abs(v) > max_tilt_degrees]
    if not tilted:
        return ""
    return (f"Your baseline is tilted ({', '.join(tilted)}). If you weren't sitting level, "
            "recalibrate; if the camera is off to one side, this is fine.")


def build_baseline(samples: list[PostureSample], recorded_at: str) -> Baseline:
    """Median of each measurement, so a few bad frames don't skew the baseline."""
    if not samples:
        raise ValueError("no samples to build a baseline from")
    return check_baseline(Baseline(
        neck_ratio=median(s.neck_ratio for s in samples),
        shoulder_width=median(s.shoulder_width for s in samples),
        shoulder_tilt=median(s.shoulder_tilt for s in samples),
        head_tilt=median(s.head_tilt for s in samples),
        recorded_at=recorded_at,
    ))


def baseline_to_dict(b: Baseline) -> dict:
    return asdict(b)


def baseline_from_dict(d: dict) -> Baseline:
    """Parse and check a stored baseline. Raises ValueError/KeyError/TypeError if bad."""
    return check_baseline(Baseline(
        neck_ratio=float(d["neck_ratio"]),
        shoulder_width=float(d["shoulder_width"]),
        shoulder_tilt=float(d["shoulder_tilt"]),
        head_tilt=float(d["head_tilt"]),
        recorded_at=str(d["recorded_at"]),
    ))
