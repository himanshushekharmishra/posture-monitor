"""FastAPI app: REST endpoints, the /ws posture WebSocket, and the frontend files.

    python -m backend            # http://127.0.0.1:8000

Layers: protocol.py (message formats) -> session.py (pure posture logic, reusing
src/engine) -> this file (HTTP/WebSocket and I/O: baseline file, SQLite log).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.security import is_allowed_host, is_same_origin

from backend.protocol import (
    CalibrateMessage, CancelCalibrationMessage, FrameMessage, LabelMessage,
    calibration_payload, client_message, frame_payload,
)
from backend.session import PostureSession, parse_landmarks
from src.engine.calibration import baseline_to_dict
from src.schemas.models import Baseline
from src.tools.baseline_store import load_baseline, save_baseline
from src.tools.logger import SessionLogger
from src.tools.notifier import AlertNotifier

log = logging.getLogger("posture.web")

# Settings the browser needs. Thresholds stay server-side; these are for display.
PUBLIC_SETTINGS = (
    "process_fps", "min_visibility", "slouch_threshold", "persist_seconds",
    "cooldown_minutes", "away_timeout_seconds", "calibration_seconds",
    "calibration_countdown_seconds",
)


@dataclass
class Shared:
    """State shared by every connection (this is a single-user local app)."""

    baseline: Baseline | None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def create_app(
    settings: dict, root: Path, clock: Callable[[], float] = time.monotonic
) -> FastAPI:
    baseline_path = root / settings["baseline_path"]
    db_path = root / settings["db_path"]
    model_path = root / settings["model_path"]
    frontend_dir = root / "frontend"
    shared = Shared(baseline=load_baseline(baseline_path))
    notifier = AlertNotifier(root / settings["alerts_path"],
                             int(settings["notification_timeout_seconds"]))

    app = FastAPI(title="Posture Monitor", version="1.0",
                  description="Posture scoring over landmarks sent by the browser.")
    app.state.shared = shared
    allowed_hosts = list(settings["web_allowed_hosts"])

    @app.middleware("http")
    async def check_host(request: Request, call_next: Callable) -> Response:
        """Refuse requests addressed to another hostname (DNS rebinding)."""
        if not is_allowed_host(request.headers.get("host"), allowed_hosts):
            return PlainTextResponse("Host not allowed", status_code=400)
        return await call_next(request)

    def with_logger(fn: Callable[[SessionLogger], object]) -> object:
        lg = SessionLogger(db_path)
        try:
            return fn(lg)
        finally:
            lg.close()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "calibrated": shared.baseline is not None,
                "model_available": model_path.is_file()}

    @app.get("/api/config")
    def config() -> dict:
        return {k: settings[k] for k in PUBLIC_SETTINGS}

    @app.get("/api/baseline")
    def get_baseline() -> dict:
        if shared.baseline is None:
            raise HTTPException(404, "Not calibrated yet")
        return baseline_to_dict(shared.baseline)

    @app.get("/api/stats")
    def stats() -> dict:
        def read(lg: SessionLogger) -> dict:
            s = lg.label_summary()
            return {
                "alerts_today": lg.alerts_today(),
                "labels": {"correct": s.correct, "false_alarm": s.false_alarm,
                           "missed": s.missed, "precision": s.precision,
                           "minutes": round(s.minutes, 1)},
                "recent_sessions": lg.recent_sessions(10),
            }
        return with_logger(read)  # type: ignore[return-value]

    @app.get("/model/pose_landmarker.task")
    def model() -> FileResponse:
        """The same pose model the desktop app uses, so the browser needs no download."""
        if not model_path.is_file():
            raise HTTPException(404, f"Model missing: run scripts\\setup.ps1 ({model_path.name})")
        return FileResponse(model_path, media_type="application/octet-stream")

    @app.websocket("/ws")
    async def posture_socket(ws: WebSocket) -> None:
        host = ws.headers.get("host")
        origin = ws.headers.get("origin")
        if not is_allowed_host(host, allowed_hosts) or not is_same_origin(origin, host):
            log.warning("Refused WebSocket from origin %r to host %r", origin, host)
            await ws.close(code=1008)  # policy violation
            return
        await ws.accept()
        logger = SessionLogger(db_path)
        logger.start_session()
        session = PostureSession(settings, shared.baseline)
        last_alert_id: int | None = None
        label_counts = {"correct": 0, "false_alarm": 0, "missed": 0}
        pose_ms_total, pose_frames = 0.0, 0
        alerts_today = logger.alerts_today()
        log.info("Web session %s connected", logger.session_id)

        async def error(message: str) -> None:
            await ws.send_json({"type": "error", "message": message})

        await ws.send_json({"type": "hello", "config": config(),
                            "calibrated": shared.baseline is not None,
                            "alerts_today": alerts_today})
        try:
            while True:
                raw = await ws.receive_json()
                try:
                    msg = client_message.validate_python(raw)
                except ValidationError as e:
                    await error(f"Bad message: {e.errors()[0]['msg']}")
                    continue

                if isinstance(msg, FrameMessage):
                    try:
                        landmarks = parse_landmarks(msg.landmarks)
                    except ValueError as e:
                        await error(str(e))
                        continue
                    if msg.pose_ms is not None:
                        pose_ms_total += msg.pose_ms
                        pose_frames += 1
                    # A baseline made in another tab or by the desktop app applies here too.
                    if shared.baseline is not session.baseline and not session.calibrating:
                        session.set_baseline(shared.baseline)
                    result = session.handle_frame(landmarks, clock(), _now_iso())
                    if result.new_baseline is not None:
                        save_baseline(result.new_baseline, baseline_path)
                        shared.baseline = result.new_baseline
                        log.info("Baseline saved from web calibration")
                    event_id = (logger.log_event(result.event, result.score)
                                if result.event else None)
                    alert = None
                    if result.alert:
                        last_alert_id = event_id
                        alerts_today = logger.alerts_today()
                        alert = {"title": notifier.title, "message": notifier.next_message()}
                    await ws.send_json(frame_payload(
                        result, alert, shared.baseline is not None, alerts_today))

                elif isinstance(msg, CalibrateMessage):
                    status = session.start_calibration(clock())
                    await ws.send_json({"type": "calibration", **calibration_payload(status)})

                elif isinstance(msg, CancelCalibrationMessage):
                    session.cancel_calibration()
                    await ws.send_json({"type": "calibration", "phase": "cancelled",
                                        "seconds_left": 0, "samples": 0,
                                        "message": "Calibration cancelled."})

                elif isinstance(msg, LabelMessage):
                    if msg.kind != "missed" and last_alert_id is None:
                        await error("No alert to label yet")
                        continue
                    logger.label(msg.kind, None if msg.kind == "missed" else last_alert_id)
                    if msg.kind != "missed":
                        last_alert_id = None  # one answer per alert
                    label_counts[msg.kind] += 1
                    await ws.send_json({"type": "labelled", "kind": msg.kind,
                                        "counts": label_counts})
        except WebSocketDisconnect:
            pass
        finally:
            avg_pose = pose_ms_total / pose_frames if pose_frames else None
            logger.end_session(avg_cpu=None, avg_latency_ms=avg_pose)  # CPU is the browser's
            logger.close()
            log.info("Web session %s closed", logger.session_id)

    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
