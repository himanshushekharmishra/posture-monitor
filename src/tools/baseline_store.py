"""Read/write the calibrated baseline (data/output/baseline.json).

Kept apart from calibrate_flow so code that only needs the file (the web backend)
doesn't import OpenCV or MediaPipe.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

from src.engine.calibration import baseline_from_dict, baseline_to_dict
from src.schemas.models import Baseline

log = logging.getLogger("posture")


def save_baseline(b: Baseline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(baseline_to_dict(b), indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic, so a reader never sees a half-written file


class BaselineWatcher:
    """Notice when baseline.json changes on disk (calibrated by the other app).

    The desktop app and the web server are separate processes sharing one file;
    each polls it at most every `check_every` seconds (one stat call).
    """

    def __init__(self, path: Path, check_every: float = 2.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.path = path
        self.check_every = check_every
        self._clock = clock
        self._stamp = self._stat()
        self._next_check = clock() + check_every

    def _stat(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def mark_current(self) -> None:
        """Call after writing the file yourself, so it isn't reported as a change."""
        self._stamp = self._stat()

    def poll(self) -> tuple[bool, Baseline | None]:
        """(changed, baseline). baseline is None if the file was deleted or is unreadable."""
        now = self._clock()
        if now < self._next_check:
            return False, None
        self._next_check = now + self.check_every
        stamp = self._stat()
        if stamp == self._stamp:
            return False, None
        self._stamp = stamp
        return True, load_baseline(self.path)


def load_baseline(path: Path) -> Baseline | None:
    if not path.is_file():
        return None
    try:
        return baseline_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Ignoring unreadable baseline %s: %s", path, e)
        return None
