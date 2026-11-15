"""Read/write the calibrated baseline (data/output/baseline.json).

Kept apart from calibrate_flow so code that only needs the file (the web backend)
doesn't import OpenCV or MediaPipe.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.engine.calibration import baseline_from_dict, baseline_to_dict
from src.schemas.models import Baseline

log = logging.getLogger("posture")


def save_baseline(b: Baseline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(baseline_to_dict(b), indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic, so a reader never sees a half-written file


def load_baseline(path: Path) -> Baseline | None:
    if not path.is_file():
        return None
    try:
        return baseline_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Ignoring unreadable baseline %s: %s", path, e)
        return None
