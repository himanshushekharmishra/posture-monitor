"""Main loop: capture -> pose -> features -> state -> notify/log.  Phase 1 onward."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from src.engine.features import deviation_score, extract_features
from src.schemas.models import Baseline, Point
from src.tools.capture import Camera
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle, LatencyTimer
from src.workflows.calibrate_flow import load_baseline

WINDOW = "Posture Monitor (debug) - press q or Esc to quit"
QUIT_KEYS = {ord("q"), 27}


def _describe(
    landmarks: list[Point] | None, baseline: Baseline | None, settings: dict
) -> list[str]:
    """Human-readable feature lines for the console and the debug overlay."""
    if not landmarks:
        return ["no person"]
    f = extract_features(landmarks, baseline)
    if f.visibility < float(settings["min_visibility"]):
        return [f"low visibility ({f.visibility:.2f})"]
    lines = [
        f"neck {f.neck_ratio:.3f}  lean {f.lean_ratio:.2f}",
        f"tilt sh {f.shoulder_tilt:+.1f}  head {f.head_tilt:+.1f}",
    ]
    if baseline:
        score = deviation_score(f, baseline, settings)
        flag = "SLOUCH" if score >= float(settings["slouch_threshold"]) else "ok"
        lines.append(f"score {score:.2f} {flag}")
    else:
        lines.append("score n/a (run --calibrate)")
    return lines


def _overlay(frame: np.ndarray, lines: list[str]) -> None:
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (10, 25 + 25 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)


def run(settings: dict, debug: bool = False, root: Path | None = None) -> None:
    root = root or Path.cwd()
    model_path = str((root / settings["model_path"]).resolve())
    min_vis = float(settings["min_visibility"])
    baseline = load_baseline(root / settings["baseline_path"])
    if baseline is None:
        print("No baseline yet; run `python -m src.main --calibrate` to get a score.")
    throttle = FrameThrottle(float(settings["process_fps"]))
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
                ts_ms = int((time.monotonic() - t0) * 1000)
                with LatencyTimer() as timer:
                    landmarks = pose.detect(frame, ts_ms)
                lines = _describe(landmarks, baseline, settings)
                print(f"latency {timer.ms:6.1f} ms  " + " | ".join(lines), flush=True)

                if debug:
                    if landmarks:
                        draw_skeleton(frame, landmarks, min_vis)
                    _overlay(frame, [f"{timer.ms:.0f} ms", *lines])
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
