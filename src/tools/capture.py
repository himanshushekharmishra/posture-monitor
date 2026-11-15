"""OpenCV webcam wrapper.  Phase 1.  Frames are never written to disk."""
from __future__ import annotations

import sys
from types import TracebackType

import cv2
import numpy as np


class Camera:
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
