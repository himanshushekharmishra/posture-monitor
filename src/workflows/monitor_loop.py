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
from src.tools.capture import open_source
from src.tools.examples import save_example
from src.tools.logger import SessionLogger
from src.tools.notifier import AlertNotifier, notify
from src.tools.pose import PoseEstimator, draw_skeleton
from src.utils.timing import FrameThrottle, LatencyTimer
from src.workflows import calibrate_flow
from src.workflows.calibrate_flow import load_baseline

log = logging.getLogger("posture")

WINDOW = "Posture Monitor (debug) - q/Esc quit, s save landmarks"
QUIT_KEYS = {ord("q"), 27}
SAVE_KEY = ord("s")
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
                try:
                    self.on_status(new)
                except Exception:  # a tray hiccup must never stop monitoring
                    log.exception("Status listener failed")


def _recalibrate(settings: dict, root: Path, tray: bool) -> Baseline | None:
    """Run calibration; on failure (e.g. camera in use) log, tell the user, carry on."""
    try:
        return calibrate_flow.run(settings, root=root)
    except (RuntimeError, OSError) as e:
        log.warning("Calibration failed: %s", e)
        if tray:
            notify("Posture Monitor", f"Couldn't calibrate: {e}. Close other apps using the "
                                      "camera and try Recalibrate again.")
        return None


class AlertLabeller:
    """Keys for a --label session: after an alert, y = it was right, n = false alarm.
    m at any time = "I was slouching and got no alert". Each key returns
    (kind, alert event id or None) for the logger, or None if nothing to record."""

    YES, NO, MISSED = ord("y"), ord("n"), ord("m")

    def __init__(self) -> None:
        self.pending: int | None = None
        self.has_pending = False
        self.counts = {"correct": 0, "false_alarm": 0, "missed": 0}

    def alert_fired(self, event_id: int | None) -> None:
        self.pending, self.has_pending = event_id, True

    def handle_key(self, key: int) -> tuple[str, int | None] | None:
        if key in (self.YES, self.NO) and self.has_pending:
            kind = "correct" if key == self.YES else "false_alarm"
            result = (kind, self.pending)
            self.pending, self.has_pending = None, False
        elif key == self.MISSED:
            kind, result = "missed", ("missed", None)
        else:
            return None
        self.counts[kind] += 1
        return result

    def overlay_lines(self) -> list[str]:
        c = self.counts
        lines = [f"labels: {c['correct']} right, {c['false_alarm']} wrong, "
                 f"{c['missed']} missed (m = missed slouch)"]
        if self.has_pending:
            lines.insert(0, ">> ALERT - was it right? y = yes, n = no")
        return lines


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
    video: Path | None = None,
    tray: bool = False,
    label: bool = False,
) -> None:
    """Run until stopped. `video` replaces the webcam with a recording (stops at its end);
    `tray` means a tray icon is attached (only changes wording and the first-run hint);
    `label` (needs debug) lets the user mark alerts right/wrong to measure precision."""
    root = root or Path.cwd()
    control = control or MonitorControl()
    labeller = AlertLabeller() if label and debug else None
    model_path = str((root / settings["model_path"]).resolve())
    baseline_path = root / settings["baseline_path"]
    min_vis = float(settings["min_visibility"])
    retry_seconds = float(settings["camera_retry_seconds"])
    baseline = load_baseline(baseline_path)
    uncalibrated_note = "not calibrated - use Recalibrate" if tray else "not calibrated"
    if baseline is None:
        log.warning("No baseline yet; run `python -m src.main --calibrate`. Alerts are off.")
        if tray:
            notify("Posture Monitor", "Not calibrated yet. Choose Recalibrate in the tray menu.")
    if video is not None:
        log.info("Reading frames from video %s instead of the webcam", video)
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
                    new = _recalibrate(settings, root, tray)
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
                    cam = open_source(settings, video)
                except RuntimeError as e:
                    if video is not None:
                        raise  # a broken file won't fix itself; don't retry
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
                            if cam.ended:
                                log.info("Video finished")
                                control.stop()
                                break
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
                        event_id = None
                        if machine.event:
                            log.info("event %s (score %s)", machine.event,
                                     "n/a" if smoothed is None else f"{smoothed:.2f}")
                            event_id = logger.log_event(machine.event, smoothed)
                        if should_alert:
                            log.info("alert: %s", notifier.alert())
                            if labeller:
                                labeller.alert_fired(event_id)
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
                            extra = labeller.overlay_lines() if labeller else []
                            _overlay(frame, [head, *lines, f"{timer.ms:.0f} ms", *extra],
                                     STATE_COLORS[state])
                            cv2.imshow(WINDOW, frame)
                            key = cv2.waitKey(1) & 0xFF
                            closed = cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
                            if key in QUIT_KEYS or closed:
                                control.stop()
                            elif labeller and (labelled := labeller.handle_key(key)):
                                kind, alert_id = labelled
                                logger.label(kind, alert_id)
                                log.info("label: %s", kind)
                            elif key == SAVE_KEY:
                                if landmarks:
                                    path = save_example(root / settings["examples_path"],
                                                        landmarks)
                                    log.info("Saved landmarks (no image) to %s", path)
                                else:
                                    log.info("No person in frame; nothing to save")
    except KeyboardInterrupt:
        control.stop()
    finally:
        if debug:
            cv2.destroyAllWindows()
        # Process CPU over the session, as a share of the whole machine.
        avg_cpu = proc.cpu_percent(None) / (psutil.cpu_count() or 1)
        avg_latency = latency_total / frames if frames else None
        logger.end_session(avg_cpu, avg_latency)
        if labeller:
            s = logger.label_summary(logger.session_id)
            p = "n/a" if s.precision is None else f"{s.precision:.0%}"
            log.info("Labelled session: %d correct, %d false alarms, %d missed; precision %s "
                     "over %.0f min", s.correct, s.false_alarm, s.missed, p, s.minutes)
        logger.close()
        log.info(
            "Monitoring stopped: %d frames, avg latency %s ms, avg CPU %.1f%%",
            frames, "n/a" if avg_latency is None else f"{avg_latency:.1f}", avg_cpu,
        )


def run_headless(settings: dict, root: Path | None = None) -> None:
    """Monitor in a background thread with a tray icon on the main thread."""
    from src.tools import single_instance
    from src.tools.tray import TrayApp

    if not single_instance.acquire():
        log.warning("Another Posture Monitor is already running; exiting")
        notify("Posture Monitor", "Already running. Look for its icon in the system tray.")
        return
    control = MonitorControl()
    tray = TrayApp(
        on_toggle_pause=control.toggle_pause,
        on_recalibrate=control.request_recalibrate,
        on_quit=control.stop,
    )
    control.on_status = tray.set_status

    def worker() -> None:
        try:
            run(settings, debug=False, root=root, control=control, tray=True)
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
