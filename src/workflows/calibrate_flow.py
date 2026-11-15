"""Record baseline while the user sits upright.  Phase 2."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from src.engine.calibration import baseline_from_dict, baseline_to_dict, build_baseline
from src.engine.features import measure
from src.schemas.models import Baseline, PostureSample
from src.tools.capture import Camera
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle

WINDOW = "Posture Monitor - calibration (Esc to cancel)"


def save_baseline(b: Baseline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline_to_dict(b), indent=2), encoding="utf-8")


def load_baseline(path: Path) -> Baseline | None:
    if not path.is_file():
        return None
    try:
        return baseline_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as e:
        print(f"Ignoring unreadable baseline {path}: {e}")
        return None


def _show(frame: np.ndarray, text: str) -> bool:
    """Show the preview with a caption. Returns False if the user cancelled."""
    cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow(WINDOW, frame)
    key = cv2.waitKey(1) & 0xFF
    return key != 27 and cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1


def run(settings: dict, root: Path | None = None, show_window: bool = True) -> Baseline | None:
    root = root or Path.cwd()
    model_path = str((root / settings["model_path"]).resolve())
    baseline_path = root / settings["baseline_path"]
    min_vis = float(settings["min_visibility"])
    countdown = float(settings["calibration_countdown_seconds"])
    duration = float(settings["calibration_seconds"])
    min_samples = int(settings["calibration_min_samples"])
    throttle = FrameThrottle(float(settings["process_fps"]))

    samples: list[PostureSample] = []
    print(f"Sit upright and face the camera. Recording starts in {countdown:.0f} s.")
    t0 = time.monotonic()
    with Camera(
        settings["camera_index"], settings["frame_width"], settings["frame_height"]
    ) as cam, PoseEstimator(model_path) as pose:
        try:
            while True:
                throttle.wait()
                elapsed = time.monotonic() - t0
                if elapsed >= countdown + duration:
                    break
                frame = cam.read()
                if frame is None:
                    continue
                landmarks = pose.detect(frame, int(elapsed * 1000))
                recording = elapsed >= countdown
                if landmarks:
                    s = measure(landmarks)
                    if recording and s.visibility >= min_vis:
                        samples.append(s)
                if show_window:
                    if landmarks:
                        draw_skeleton(frame, landmarks, min_vis)
                    caption = (
                        f"Recording... {countdown + duration - elapsed:.1f}s  ({len(samples)})"
                        if recording
                        else f"Sit upright - starting in {countdown - elapsed:.1f}s"
                    )
                    if not _show(frame, caption):
                        print("Calibration cancelled.")
                        return None
        except KeyboardInterrupt:
            print("Calibration cancelled.")
            return None
        finally:
            if show_window:
                cv2.destroyAllWindows()

    if len(samples) < min_samples:
        print(
            f"Only {len(samples)} good frames (need {min_samples}). Make sure your "
            "ears and shoulders are visible and well lit, then try again."
        )
        return None
    baseline = build_baseline(samples, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    save_baseline(baseline, baseline_path)
    print(
        f"Saved baseline from {len(samples)} frames to {baseline_path}: "
        f"neck_ratio={baseline.neck_ratio:.3f} shoulder_width={baseline.shoulder_width:.3f} "
        f"shoulder_tilt={baseline.shoulder_tilt:.1f} head_tilt={baseline.head_tilt:.1f}"
    )
    return baseline
