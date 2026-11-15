"""Main loop: capture -> pose -> features -> state -> notify/log.  Phase 1 onward."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import psutil

from src.engine.features import deviation_score, extract_features
from src.engine.state import Ema, PostureStateMachine
from src.schemas.models import Baseline, MonitorStatus, Point, PostureState
from src.tools.capture import Camera
from src.tools.logger import SessionLogger
from src.tools.notifier import AlertNotifier, notify
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle, LatencyTimer
from src.workflows import calibrate_flow
from src.workflows.calibrate_flow import load_baseline

log = logging.getLogger("posture")

WINDOW = "Posture Monitor (debug) - press q or Esc to quit"
QUIT_KEYS = {ord("q"), 27}
PAUSE_POLL_SECONDS = 0.5
STATE_COLORS = {  # BGR
    PostureState.AWAY: (160, 160, 160),
    PostureState.GOOD: (0, 200, 0),
    PostureState.SLOUCHING: (0, 200, 255),
    PostureState.ALERTED: (0, 0, 255),
}


class MonitorControl:
    """Thread-safe stop / pause / recalibrate flags plus the latest status."""

    def __init__(self, on_status: Callable[[MonitorStatus], None] | None = None) -> None:
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._recalibrate = threading.Event()
        self.on_status = on_status
        self.status = MonitorStatus()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def recalibrate_pending(self) -> bool:
        return self._recalibrate.is_set()

    def stop(self) -> None:
        self._stop.set()

    def toggle_pause(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
        else:
            self._paused.set()

    def request_recalibrate(self) -> None:
        self._recalibrate.set()

    def take_recalibrate(self) -> bool:
        if self._recalibrate.is_set():
            self._recalibrate.clear()
            return True
        return False

    def wait(self, seconds: float) -> None:
        """Sleep, but wake early if stop() is called."""
        self._stop.wait(seconds)

    def publish(self, **changes: object) -> None:
        new = replace(self.status, **changes)
        if new != self.status:
            self.status = new
            if self.on_status:
                self.on_status(new)


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


def run(
    settings: dict,
    debug: bool = False,
    root: Path | None = None,
    control: MonitorControl | None = None,
) -> None:
    root = root or Path.cwd()
    control = control or MonitorControl()
    model_path = str((root / settings["model_path"]).resolve())
    baseline_path = root / settings["baseline_path"]
    min_vis = float(settings["min_visibility"])
    retry_seconds = float(settings["camera_retry_seconds"])
    baseline = load_baseline(baseline_path)
    uncalibrated_note = "not calibrated - use Recalibrate" if not debug else "not calibrated"
    if baseline is None:
        log.warning("No baseline yet; run `python -m src.main --calibrate`. Alerts are off.")
        if not debug:
            notify("Posture Monitor", "Not calibrated yet. Choose Recalibrate in the tray menu.")
    throttle = FrameThrottle(float(settings["process_fps"]))
    ema = Ema(float(settings["ema_alpha"]))
    machine = PostureStateMachine.from_settings(settings)
    notifier = AlertNotifier(
        root / settings["alerts_path"], int(settings["notification_timeout_seconds"])
    )
    logger = SessionLogger(root / settings["db_path"])
    logger.start_session()
    proc = psutil.Process()
    proc.cpu_percent(None)  # start the CPU measurement window
    latency_total, frames = 0.0, 0
    camera_note = ""
    control.publish(
        alerts_today=logger.alerts_today(), note="" if baseline else uncalibrated_note
    )
    t0 = time.monotonic()
    log.info("Monitoring started (session %s)", logger.session_id)

    def base_note() -> str:
        return camera_note or ("" if baseline else uncalibrated_note)

    try:
        with PoseEstimator(model_path) as pose:
            while not control.stopped:
                if control.take_recalibrate():
                    control.publish(note="calibrating", paused=False)
                    log.info("Recalibrating")
                    new = calibrate_flow.run(settings, root=root)
                    if new is not None:
                        baseline = new
                        machine.reset()
                        ema.reset()
                    control.publish(state=machine.state, note=base_note())
                    continue

                if control.paused:
                    if control.status.paused is False:
                        log.info("Paused")
                        machine.reset()
                        ema.reset()
                    control.publish(state=machine.state, paused=True)
                    control.wait(PAUSE_POLL_SECONDS)
                    continue
                if control.status.paused:
                    log.info("Resumed")
                control.publish(paused=False)

                try:
                    cam = Camera(
                        settings["camera_index"], settings["frame_width"],
                        settings["frame_height"],
                    )
                except RuntimeError as e:
                    if not camera_note:
                        log.warning("%s; retrying every %.0f s", e, retry_seconds)
                    camera_note = "camera unavailable"
                    control.publish(note=base_note())
                    control.wait(retry_seconds)
                    continue

                with cam:
                    camera_note = ""
                    control.publish(note=base_note())
                    misses = 0
                    while not (
                        control.stopped or control.paused or control.recalibrate_pending
                    ):
                        throttle.wait()
                        frame = cam.read()
                        if frame is None:
                            misses += 1
                            if misses * throttle.interval >= retry_seconds:
                                log.warning("Camera stopped sending frames; reopening")
                                break
                            continue
                        misses = 0
                        now = time.monotonic()
                        with LatencyTimer() as timer:
                            landmarks = pose.detect(frame, int((now - t0) * 1000))
                        latency_total += timer.ms
                        frames += 1

                        raw, lines = _score_frame(landmarks, baseline, settings)
                        smoothed = ema.update(raw) if raw is not None else None
                        state, should_alert = machine.update(smoothed, now)
                        if state == PostureState.AWAY:
                            ema.reset()
                        if machine.event:
                            log.info("event %s (score %s)", machine.event,
                                     "n/a" if smoothed is None else f"{smoothed:.2f}")
                            logger.log_event(machine.event, smoothed)
                        if should_alert:
                            log.info("alert: %s", notifier.alert())
                        control.publish(
                            state=state,
                            alerts_today=logger.alerts_today()
                            if should_alert else control.status.alerts_today,
                        )

                        if debug:
                            head = state.value.upper()
                            if smoothed is not None:
                                head += f"  score {smoothed:.2f}"
                            if state in (PostureState.SLOUCHING, PostureState.ALERTED):
                                head += f"  {machine.slouch_seconds(now):.0f}s"
                            print(f"latency {timer.ms:6.1f} ms  {head} | " + " | ".join(lines),
                                  flush=True)
                            if landmarks:
                                draw_skeleton(frame, landmarks, min_vis)
                            _overlay(frame, [head, *lines, f"{timer.ms:.0f} ms"],
                                     STATE_COLORS[state])
                            cv2.imshow(WINDOW, frame)
                            key = cv2.waitKey(1) & 0xFF
                            closed = cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
                            if key in QUIT_KEYS or closed:
                                control.stop()
    except KeyboardInterrupt:
        control.stop()
    finally:
        if debug:
            cv2.destroyAllWindows()
        # Process CPU over the session, as a share of the whole machine.
        avg_cpu = proc.cpu_percent(None) / (psutil.cpu_count() or 1)
        avg_latency = latency_total / frames if frames else None
        logger.end_session(avg_cpu, avg_latency)
        logger.close()
        log.info(
            "Monitoring stopped: %d frames, avg latency %s ms, avg CPU %.1f%%",
            frames, "n/a" if avg_latency is None else f"{avg_latency:.1f}", avg_cpu,
        )


def run_headless(settings: dict, root: Path | None = None) -> None:
    """Monitor in a background thread with a tray icon on the main thread."""
    from src.tools.tray import TrayApp

    control = MonitorControl()
    tray = TrayApp(
        on_toggle_pause=control.toggle_pause,
        on_recalibrate=control.request_recalibrate,
        on_quit=control.stop,
    )
    control.on_status = tray.set_status

    def worker() -> None:
        try:
            run(settings, debug=False, root=root, control=control)
        except Exception as e:
            log.exception("Monitor crashed")
            notify("Posture Monitor stopped", f"{type(e).__name__}: {e}")
        finally:
            tray.stop()

    thread = threading.Thread(target=worker, name="monitor", daemon=True)
    thread.start()
    tray.run()
    control.stop()
    # Calibration can take a few seconds to finish; give the session time to close.
    thread.join(timeout=float(settings["calibration_seconds"])
                + float(settings["calibration_countdown_seconds"]) + 5)
