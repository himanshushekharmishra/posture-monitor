"""Main loop: capture -> pose -> features -> state -> notify/log.  Phase 1 onward."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from src.engine.features import deviation_score, extract_features
from src.engine.state import Ema, PostureStateMachine
from src.schemas.models import Baseline, Point, PostureState
from src.tools.capture import Camera
from src.tools.notifier import AlertNotifier
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle, LatencyTimer
from src.workflows.calibrate_flow import load_baseline

WINDOW = "Posture Monitor (debug) - press q or Esc to quit"
QUIT_KEYS = {ord("q"), 27}
STATE_COLORS = {  # BGR
    PostureState.AWAY: (160, 160, 160),
    PostureState.GOOD: (0, 200, 0),
    PostureState.SLOUCHING: (0, 200, 255),
    PostureState.ALERTED: (0, 0, 255),
}


def _score_frame(
    landmarks: list[Point] | None, baseline: Baseline | None, settings: dict
) -> tuple[float | None, list[str]]:
    """Raw deviation score (None if no usable person) and human-readable lines."""
    if not landmarks:
        return None, ["no person"]
    f = extract_features(landmarks, baseline)
    if f.visibility < float(settings["min_visibility"]):
        return None, [f"low visibility ({f.visibility:.2f})"]
    lines = [
        f"neck {f.neck_ratio:.3f}  lean {f.lean_ratio:.2f}",
        f"tilt sh {f.shoulder_tilt:+.1f}  head {f.head_tilt:+.1f}",
    ]
    if baseline is None:
        return None, [*lines, "score n/a (run --calibrate)"]
    return deviation_score(f, baseline, settings), lines


def _overlay(frame: np.ndarray, lines: list[str], color: tuple[int, int, int]) -> None:
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (10, 25 + 25 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    color if i == 0 else (255, 255, 255), 2, cv2.LINE_AA)


def run(settings: dict, debug: bool = False, root: Path | None = None) -> None:
    root = root or Path.cwd()
    model_path = str((root / settings["model_path"]).resolve())
    min_vis = float(settings["min_visibility"])
    baseline = load_baseline(root / settings["baseline_path"])
    if baseline is None:
        print("No baseline yet; run `python -m src.main --calibrate`. Alerts are off.")
    throttle = FrameThrottle(float(settings["process_fps"]))
    ema = Ema(float(settings["ema_alpha"]))
    machine = PostureStateMachine.from_settings(settings)
    notifier = AlertNotifier(
        root / settings["alerts_path"], int(settings["notification_timeout_seconds"])
    )
    t0 = time.monotonic()

    with Camera(
        settings["camera_index"], settings["frame_width"], settings["frame_height"]
    ) as cam, PoseEstimator(model_path) as pose:
        if debug:
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        try:
            while True:
                throttle.wait()
                frame = cam.read()
                if frame is None:
                    print("camera returned no frame; retrying")
                    continue
                now = time.monotonic()
                with LatencyTimer() as timer:
                    landmarks = pose.detect(frame, int((now - t0) * 1000))

                raw, lines = _score_frame(landmarks, baseline, settings)
                smoothed = ema.update(raw) if raw is not None else None
                state, should_alert = machine.update(smoothed, now)
                if state == PostureState.AWAY:
                    ema.reset()
                if should_alert:
                    print(f"ALERT: {notifier.alert()}", flush=True)
                if machine.event:
                    print(f"[{machine.event}]", flush=True)

                head = f"{state.value.upper()}"
                if smoothed is not None:
                    head += f"  score {smoothed:.2f}"
                if state in (PostureState.SLOUCHING, PostureState.ALERTED):
                    head += f"  {machine.slouch_seconds(now):.0f}s"
                print(f"latency {timer.ms:6.1f} ms  {head} | " + " | ".join(lines), flush=True)

                if debug:
                    if landmarks:
                        draw_skeleton(frame, landmarks, min_vis)
                    _overlay(frame, [head, *lines, f"{timer.ms:.0f} ms"], STATE_COLORS[state])
                    cv2.imshow(WINDOW, frame)
                    key = cv2.waitKey(1) & 0xFF
                    closed = cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
                    if key in QUIT_KEYS or closed:
                        break
        except KeyboardInterrupt:
            pass
        finally:
            if debug:
                cv2.destroyAllWindows()
