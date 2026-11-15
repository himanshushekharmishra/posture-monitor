"""OpenCV webcam and video-file sources.  Phase 1.  Frames are never written to disk."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Callable, Protocol

import cv2
import numpy as np


class FrameSource(Protocol):
    ended: bool

    def read(self) -> np.ndarray | None: ...
    def release(self) -> None: ...
    def __enter__(self) -> FrameSource: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None: ...


class Camera:
    ended = False  # a webcam never runs out

    def __init__(self, index: int, width: int, height: int) -> None:
        # DirectShow opens much faster than MSMF on Windows.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, backend)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open camera index {index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # We read at a low FPS; keep the driver buffer small so frames aren't stale.
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self) -> np.ndarray | None:
        """Return the latest BGR frame, or None if the camera returned nothing."""
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        self._cap.release()

    def __enter__(self) -> Camera:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class VideoFile:
    """A recorded video that behaves like a live camera.

    With realtime=True each read() returns the frame that should be on screen now
    (skipping frames in between), so a 30 FPS recording read at 5 FPS plays at
    normal speed. With realtime=False each read() returns the next frame.
    `ended` turns True when the video runs out (never, with loop=True).
    """

    def __init__(
        self, path: Path, loop: bool = False, realtime: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        if not path.is_file():
            raise FileNotFoundError(f"Video not found: {path}")
        self._cap = cv2.VideoCapture(str(path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video {path}")
        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.loop = loop
        self.realtime = realtime
        self.ended = False
        self._start: float | None = None
        self._index = -1  # index of the last frame returned

    def _restart(self, now: float) -> None:
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._start = now
        self._index = -1

    def read(self) -> np.ndarray | None:
        if self.ended:
            return None
        now = self._clock()
        if self._start is None:
            self._start = now
        target = self._index + 1
        if self.realtime:
            target = max(target, int((now - self._start) * self.fps))
        restarted = False
        while self._index < target:
            if not self._cap.grab():
                if self.loop and not restarted and self._index >= 0:
                    self._restart(now)
                    restarted, target = True, 0
                    continue
                self.ended = True
                return None
            self._index += 1
        ok, frame = self._cap.retrieve()
        return frame if ok else None

    def release(self) -> None:
        self._cap.release()

    def __enter__(self) -> VideoFile:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def open_source(settings: dict, video: Path | None = None, loop: bool = False) -> FrameSource:
    """The webcam from settings, or a video file if one is given."""
    if video is not None:
        return VideoFile(video, loop=loop)
    return Camera(settings["camera_index"], settings["frame_width"], settings["frame_height"])
