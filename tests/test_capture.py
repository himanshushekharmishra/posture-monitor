import cv2
import numpy as np
import pytest

from src.tools.capture import VideoFile

STEP = 8  # brightness per frame number; 30 frames stay under 255


def write_video(path, frames=10, fps=10.0):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    assert w.isOpened()
    for i in range(frames):
        # Encode the frame number in the brightness so we can tell frames apart.
        w.write(np.full((48, 64, 3), i * STEP, np.uint8))
    w.release()


def brightness(frame):
    return int(round(frame.mean() / STEP))


def test_reads_every_frame_then_ends(tmp_path):
    path = tmp_path / "clip.avi"
    write_video(path, frames=10)
    with VideoFile(path, realtime=False) as v:
        seen = []
        while (f := v.read()) is not None:
            seen.append(brightness(f))
        assert v.ended
    assert seen == list(range(10))


def test_loop_restarts_from_the_beginning(tmp_path):
    path = tmp_path / "clip.avi"
    write_video(path, frames=4)
    with VideoFile(path, loop=True, realtime=False) as v:
        seen = [brightness(v.read()) for _ in range(9)]
        assert not v.ended
    assert seen == [0, 1, 2, 3, 0, 1, 2, 3, 0]


def test_realtime_skips_frames_to_keep_up(tmp_path):
    path = tmp_path / "clip.avi"
    write_video(path, frames=30, fps=10.0)
    clock = {"t": 100.0}
    with VideoFile(path, realtime=True, clock=lambda: clock["t"]) as v:
        first = brightness(v.read())
        clock["t"] += 0.5  # half a second later -> frame 5 at 10 FPS
        second = brightness(v.read())
    assert (first, second) == (0, 5)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        VideoFile(tmp_path / "nope.mp4")
