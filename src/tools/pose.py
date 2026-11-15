"""MediaPipe PoseLandmarker wrapper (Tasks API, VIDEO mode).  Phase 1.

Use mediapipe.tasks.python.vision.PoseLandmarker. Never mp.solutions.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from src.schemas.models import Point

POSE_CONNECTIONS: list[tuple[int, int]] = [
    (c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS
]


def silence_native_logs() -> bool:
    """Send C/C++ output on stderr (MediaPipe/LiteRT startup logs) to NUL.

    MediaPipe ignores GLOG/TF log-level variables, so this redirects file descriptor
    2 instead and points Python's sys.stderr at a copy of the original, which keeps
    Python errors, tracebacks and warnings visible. Native crash messages are hidden
    too; set QUIET_NATIVE_LOGS=false to see them. Returns False if there is no
    console (pythonw.exe) or the redirect isn't possible.
    """
    if sys.stderr is None:
        return False
    try:
        sys.stderr.flush()
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        return False
    encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
    sys.stderr = os.fdopen(saved, "w", buffering=1, encoding=encoding,
                           errors="backslashreplace")
    return True


class PoseEstimator:
    def __init__(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"Pose model not found at {path}. Run scripts\\setup.ps1 or download "
                "pose_landmarker_lite.task into models\\."
            )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> list[Point] | None:
        """Return 33 normalized landmarks for the first person, or None if nobody."""
        # VIDEO mode requires strictly increasing timestamps.
        ts = max(int(timestamp_ms), self._last_ts + 1)
        self._last_ts = ts
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts)
        if not result.pose_landmarks:
            return None
        return [
            Point(lm.x, lm.y, lm.visibility if lm.visibility is not None else 0.0)
            for lm in result.pose_landmarks[0]
        ]

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> PoseEstimator:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def draw_skeleton(frame_bgr: np.ndarray, landmarks: list[Point], min_visibility: float) -> None:
    """Draw landmarks and connections in place on a BGR frame (display only)."""
    h, w = frame_bgr.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in landmarks]
    visible = [p.visibility >= min_visibility for p in landmarks]
    for a, b in POSE_CONNECTIONS:
        if visible[a] and visible[b]:
            cv2.line(frame_bgr, pts[a], pts[b], (0, 200, 0), 2, cv2.LINE_AA)
    for (x, y), ok in zip(pts, visible):
        if ok:
            cv2.circle(frame_bgr, (x, y), 3, (0, 0, 255), -1, cv2.LINE_AA)
