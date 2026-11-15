"""Average features over N seconds into a Baseline.  Phase 2.  Pure logic."""
from __future__ import annotations

from dataclasses import asdict
from statistics import median

from src.schemas.models import Baseline, PostureSample


def build_baseline(samples: list[PostureSample], recorded_at: str) -> Baseline:
    """Median of each measurement, so a few bad frames don't skew the baseline."""
    if not samples:
        raise ValueError("no samples to build a baseline from")
    return Baseline(
        neck_ratio=median(s.neck_ratio for s in samples),
        shoulder_width=median(s.shoulder_width for s in samples),
        shoulder_tilt=median(s.shoulder_tilt for s in samples),
        head_tilt=median(s.head_tilt for s in samples),
        recorded_at=recorded_at,
    )


def baseline_to_dict(b: Baseline) -> dict:
    return asdict(b)


def baseline_from_dict(d: dict) -> Baseline:
    return Baseline(
        neck_ratio=float(d["neck_ratio"]),
        shoulder_width=float(d["shoulder_width"]),
        shoulder_tilt=float(d["shoulder_tilt"]),
        head_tilt=float(d["head_tilt"]),
        recorded_at=str(d["recorded_at"]),
    )
