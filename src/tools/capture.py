"""OpenCV webcam wrapper.  Phase 1.  Frames are never written to disk."""


class Camera:
    def __init__(self, index: int, width: int, height: int) -> None:
        raise NotImplementedError
