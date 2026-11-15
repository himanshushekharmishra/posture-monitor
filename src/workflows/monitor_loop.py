"""Main loop: capture -> pose -> features -> state -> notify/log.  Phase 1 onward."""
from __future__ import annotations

import time
from pathlib import Path

import cv2

from src.tools.capture import Camera
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle, LatencyTimer

WINDOW = "Posture Monitor (debug) - press q or Esc to quit"
QUIT_KEYS = {ord("q"), 27}


def run(settings: dict, debug: bool = False, root: Path | None = None) -> None:
    root = root or Path.cwd()
    model_path = str((root / settings["model_path"]).resolve())
    min_vis = float(settings["min_visibility"])
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
                status = "person" if landmarks else "no person"
                print(f"latency {timer.ms:6.1f} ms  {status}", flush=True)

                if debug:
                    if landmarks:
                        draw_skeleton(frame, landmarks, min_vis)
                    cv2.putText(
                        frame, f"{timer.ms:.0f} ms", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA,
                    )
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
