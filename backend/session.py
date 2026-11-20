"""Per-connection posture logic for the web app.  Pure: no sockets, files or clock.

A browser sends landmarks; PostureSession turns them into the same features, score,
EMA and state machine the desktop app uses (src/engine), and runs calibration when
asked. The caller (backend/app.py) passes the time in and does all I/O: saving the
baseline, logging events, picking alert texts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from src.engine.calibration import build_baseline, tilt_warning
from src.engine.features import deviation_score, extract_features, measure
from src.engine.state import Ema, PostureStateMachine
from src.schemas.models import Baseline, Point, PostureSample, PostureState


class CalibrationPhase(str, Enum):
    COUNTDOWN = "countdown"
    RECORDING = "recording"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class CalibrationStatus:
    phase: CalibrationPhase
    seconds_left: float
    samples: int
    message: str = ""


@dataclass(frozen=True)
class FrameResult:
    state: PostureState
    score: float | None  # smoothed; None when there is no usable person or baseline
    slouch_seconds: float
    features: dict[str, float] | None
    note: str  # "", "no person", "low visibility", "not calibrated"
    event: str | None  # state machine event this frame, if any
    alert: bool
    calibration: CalibrationStatus | None
    new_baseline: Baseline | None = None  # set on the frame where calibration finishes


@dataclass
class _Calibration:
    started: float
    samples: list[PostureSample] = field(default_factory=list)


class PostureSession:
    def __init__(self, settings: dict, baseline: Baseline | None) -> None:
        self.settings = settings
        self.baseline = baseline
        self.min_vis = float(settings["min_visibility"])
        self.countdown = float(settings["calibration_countdown_seconds"])
        self.duration = float(settings["calibration_seconds"])
        self.min_samples = int(settings["calibration_min_samples"])
        self.ema = Ema(float(settings["ema_alpha"]))
        self.machine = PostureStateMachine.from_settings(settings)
        self._calibration: _Calibration | None = None

    @property
    def calibrating(self) -> bool:
        return self._calibration is not None

    def start_calibration(self, now: float) -> CalibrationStatus:
        self._calibration = _Calibration(started=now)
        return CalibrationStatus(CalibrationPhase.COUNTDOWN, self.countdown + self.duration, 0,
                                 "Sit upright and face the camera.")

    def cancel_calibration(self) -> None:
        self._calibration = None

    def set_baseline(self, baseline: Baseline | None) -> None:
        self.baseline = baseline
        self.ema.reset()
        self.machine.reset()

    def _calibration_step(
        self, landmarks: list[Point] | None, now: float, recorded_at: str
    ) -> tuple[CalibrationStatus, Baseline | None]:
        cal = self._calibration
        assert cal is not None
        elapsed = now - cal.started
        left = max(0.0, self.countdown + self.duration - elapsed)
        if elapsed < self.countdown:
            return CalibrationStatus(CalibrationPhase.COUNTDOWN, left, 0,
                                     "Sit upright and face the camera."), None
        if elapsed < self.countdown + self.duration:
            if landmarks:
                s = measure(landmarks)
                if s.visibility >= self.min_vis:
                    cal.samples.append(s)
            return CalibrationStatus(CalibrationPhase.RECORDING, left, len(cal.samples),
                                     "Recording - hold still."), None
        self._calibration = None
        if len(cal.samples) < self.min_samples:
            return CalibrationStatus(
                CalibrationPhase.FAILED, 0, len(cal.samples),
                f"Only {len(cal.samples)} good frames (need {self.min_samples}). Make sure "
                "your ears and shoulders are visible and well lit, then try again.",
            ), None
        try:
            baseline = build_baseline(cal.samples, recorded_at)
        except ValueError as e:
            return CalibrationStatus(CalibrationPhase.FAILED, 0, len(cal.samples),
                                     f"Calibration failed: {e}."), None
        self.set_baseline(baseline)
        warning = tilt_warning(baseline, float(self.settings["calibration_max_tilt_degrees"]))
        return CalibrationStatus(CalibrationPhase.DONE, 0, len(cal.samples),
                                 f"Calibrated. {warning}".strip()), baseline

    def handle_frame(
        self, landmarks: list[Point] | None, now: float, recorded_at: str = ""
    ) -> FrameResult:
        """Process one frame. `recorded_at` timestamps a baseline made on this frame."""
        calibration, new_baseline = (None, None)
        if self._calibration is not None:
            calibration, new_baseline = self._calibration_step(landmarks, now, recorded_at)

        features, raw, note = None, None, ""
        if not landmarks:
            note = "no person"
        else:
            f = extract_features(landmarks, self.baseline)
            if f.visibility < self.min_vis:
                note = "low visibility"
            else:
                features = {
                    "neck_ratio": f.neck_ratio, "lean_ratio": f.lean_ratio,
                    "shoulder_tilt": f.shoulder_tilt, "head_tilt": f.head_tilt,
                    "visibility": f.visibility,
                }
                if self.baseline is None:
                    note = "not calibrated"
                else:
                    raw = deviation_score(f, self.baseline, self.settings)

        # Don't judge posture while calibrating: the user is told to sit up anyway.
        if self.calibrating or calibration is not None:
            raw = None
        score = self.ema.update(raw) if raw is not None else None
        state, alert = self.machine.update(score, now)
        if state == PostureState.AWAY:
            self.ema.reset()
        return FrameResult(
            state=state,
            score=score,
            slouch_seconds=self.machine.slouch_seconds(now),
            features=features,
            note=note,
            event=self.machine.event,
            alert=alert,
            calibration=calibration,
            new_baseline=new_baseline,
        )


def parse_landmarks(raw: list[list[float]] | None) -> list[Point] | None:
    """[[x, y, visibility], ...] (33 items) -> Points. Raises ValueError if malformed."""
    if raw is None:
        return None
    if len(raw) != 33:
        raise ValueError(f"expected 33 landmarks, got {len(raw)}")
    points = []
    for item in raw:
        if len(item) < 2:
            raise ValueError("each landmark needs at least x and y")
        x, y = float(item[0]), float(item[1])
        v = float(item[2]) if len(item) > 2 else 1.0
        if not all(math.isfinite(n) for n in (x, y, v)):
            raise ValueError("landmark values must be finite numbers")
        points.append(Point(x, y, min(1.0, max(0.0, v))))
    return points
