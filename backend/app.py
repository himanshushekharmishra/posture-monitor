"""FastAPI app: accounts, REST endpoints, the /ws posture WebSocket, and the frontend.

    python -m backend            # http://127.0.0.1:8000

Layers: protocol.py (message formats) -> session.py (pure posture logic, reusing
src/engine) -> this file (HTTP/WebSocket and I/O). Accounts live in backend/auth/.

Each account has its own calibration and history. The desktop app is separate: it
keeps using data/output/baseline.json and its sessions have no owner.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.auth.routes import Auth
from backend.auth.sms import make_sender
from backend.auth.store import AuthStore, User, load_or_create_secret
from backend.history import History
from backend.insights import build_insights, summarize_session
from backend.protocol import (
    CalibrateMessage, CancelCalibrationMessage, FrameMessage, LabelMessage,
    calibration_payload, client_message, frame_payload,
)
from backend.security import is_allowed_host, is_same_origin
from backend.session import PostureSession, parse_landmarks
from src.engine.calibration import baseline_from_dict, baseline_to_dict
from src.schemas.models import Baseline
from src.tools.logger import SessionLogger
from src.tools.notifier import AlertNotifier

log = logging.getLogger("posture.web")

# Settings the browser needs. Thresholds stay server-side; these are for display.
PUBLIC_SETTINGS = (
    "process_fps", "min_visibility", "slouch_threshold", "persist_seconds",
    "cooldown_minutes", "away_timeout_seconds", "calibration_seconds",
    "calibration_countdown_seconds",
)
APP_PAGES = {"/", "/index.html"}  # need an active account
LOGIN_PAGE = "/login.html"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def security_headers(host: str) -> dict[str, str]:
    """Strict browser policy: our own scripts plus the MediaPipe CDN, no framing."""
    csp = "; ".join([
        "default-src 'self'",
        "script-src 'self' https://cdn.jsdelivr.net 'wasm-unsafe-eval'",
        "worker-src 'self' blob:",
        f"connect-src 'self' ws://{host} wss://{host} https://cdn.jsdelivr.net",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "media-src 'self' blob: mediastream:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ])
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }


class UserBaselines:
    """Each account's calibration, cached in memory and stored in the database."""

    def __init__(self, store: AuthStore) -> None:
        self.store = store
        self._cache: dict[int, Baseline | None] = {}

    def get(self, user_id: int) -> Baseline | None:
        if user_id not in self._cache:
            raw = self.store.get_baseline_json(user_id)
            try:
                self._cache[user_id] = baseline_from_dict(json.loads(raw)) if raw else None
            except (ValueError, KeyError, TypeError):
                log.warning("Ignoring unreadable baseline for account %s", user_id)
                self._cache[user_id] = None
        return self._cache[user_id]

    def save(self, user_id: int, baseline: Baseline) -> None:
        self.store.save_baseline_json(user_id, json.dumps(baseline_to_dict(baseline)))
        self._cache[user_id] = baseline


def create_app(
    settings: dict, root: Path, clock: Callable[[], float] = time.monotonic,
    sms=None, auth_store: AuthStore | None = None,
) -> FastAPI:
    db_path = root / settings["db_path"]
    model_path = root / settings["model_path"]
    face_model_path = root / settings["face_model_path"]
    frontend_dir = root / "frontend"
    store = auth_store or AuthStore(db_path, load_or_create_secret(root / settings["secret_key_path"]))
    auth = Auth(settings, store, sms if sms is not None else make_sender(settings))
    baselines = UserBaselines(store)
    notifier = AlertNotifier(root / settings["alerts_path"],
                             int(settings["notification_timeout_seconds"]))

    # No public /docs: it would need inline scripts and maps the API for attackers.
    app = FastAPI(title="Posture Monitor", version="1.1", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.auth = auth
    app.state.baselines = baselines
    allowed_hosts = list(settings["web_allowed_hosts"])

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable) -> Response:
        host = request.headers.get("host")
        # DNS rebinding: only serve requests addressed to us.
        if not is_allowed_host(host, allowed_hosts):
            return PlainTextResponse("Host not allowed", status_code=400)
        # CSRF: changes must come from our own pages, as JSON.
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            cross_site = request.headers.get("sec-fetch-site") == "cross-site"
            if cross_site or (origin is not None and not is_same_origin(origin, host)):
                return PlainTextResponse("Cross-site request refused", status_code=403)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return PlainTextResponse("Send JSON", status_code=415)
        # Pages: the app needs an active account; the login page doesn't if you have one.
        path = request.url.path
        if path in APP_PAGES:
            user = auth.current_user(request)
            if user is None:
                return RedirectResponse(LOGIN_PAGE, 302)
            if user.trial_expired(store.now()):
                return RedirectResponse(f"{LOGIN_PAGE}#trial-ended", 302)
        elif path == LOGIN_PAGE and auth.active_user(request) and "error" not in request.query_params:
            return RedirectResponse("/", 302)
        response = await call_next(request)
        for k, v in security_headers(host or "").items():
            response.headers.setdefault(k, v)
        if path in APP_PAGES or path == LOGIN_PAGE or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.endswith((".js", ".css", ".html")):
            # Check for a newer version on every load (unchanged files come back as a cheap
            # 304), so an updated app never runs with old scripts from the browser cache.
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(auth.router)

    def require_user(request: Request) -> User:
        user = auth.active_user(request)
        if user is None:
            raise HTTPException(401, "Log in to continue")
        return user

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "model_available": model_path.is_file()}

    @app.get("/api/config")
    def config() -> dict:
        return {k: settings[k] for k in PUBLIC_SETTINGS}

    @app.get("/api/baseline")
    def get_baseline(request: Request) -> dict:
        b = baselines.get(require_user(request).id)
        if b is None:
            raise HTTPException(404, "Not calibrated yet")
        return baseline_to_dict(b)

    @app.get("/api/stats")
    def stats(request: Request) -> dict:
        user = require_user(request)
        lg = SessionLogger(db_path, owner=user.id)
        try:
            s = lg.label_summary()
            return {
                "alerts_today": lg.alerts_today(),
                "labels": {"correct": s.correct, "false_alarm": s.false_alarm,
                           "missed": s.missed, "precision": s.precision,
                           "minutes": round(s.minutes, 1)},
                "recent_sessions": lg.recent_sessions(10),
            }
        finally:
            lg.close()

    # ---------- dashboard ----------
    live_sessions: set[int] = set()  # web sessions with an open socket right now

    def summaries(h: History, rows: list) -> list:
        evs = h.events([r.id for r in rows])
        by_session: dict[int, list] = {}
        for e in evs:
            by_session.setdefault(e.session_id, []).append(e)
        now = datetime.now().astimezone()
        return [summarize_session(r, by_session.get(r.id, []), now, frozenset(live_sessions))
                for r in rows]

    @app.get("/api/sessions")
    def list_sessions(request: Request, limit: int = Query(20, ge=1, le=100),
                      before: int | None = Query(None, ge=1)) -> dict:
        user = require_user(request)
        with History(db_path, user.id) as h:
            rows = h.sessions(limit=limit + 1, before_id=before)
            page = summaries(h, rows[:limit])
        return {"sessions": [s.as_dict() for s in page],
                "next_before": page[-1].id if len(rows) > limit else None}

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: int, request: Request) -> dict:
        user = require_user(request)
        with History(db_path, user.id) as h:
            row = h.session(session_id)
            if row is None:
                raise HTTPException(404, "Session not found")
            return summaries(h, [row])[0].as_dict(with_events=True)

    @app.get("/api/insights")
    def insights(request: Request, days: int = Query(14, ge=1, le=90)) -> dict:
        user = require_user(request)
        with History(db_path, user.id) as h:
            all_rows = summaries(h, h.sessions())
            evs = h.events()
        return build_insights(all_rows, evs, datetime.now().astimezone().date(), days)

    @app.get("/model/pose_landmarker.task")
    def model() -> FileResponse:
        """The same pose model the desktop app uses, so the browser needs no download."""
        if not model_path.is_file():
            raise HTTPException(404, f"Model missing: run scripts\\setup.ps1 ({model_path.name})")
        return FileResponse(model_path, media_type="application/octet-stream")

    @app.get("/model/face_landmarker.task")
    def face_model() -> FileResponse:
        """478-point face mesh for the page's hologram view. The face points are only
        drawn in the browser; they are never sent back here."""
        if not face_model_path.is_file():
            raise HTTPException(404, "Face model missing: run scripts\\setup.ps1 "
                                     f"({face_model_path.name})")
        return FileResponse(face_model_path, media_type="application/octet-stream")

    @app.websocket("/ws")
    async def posture_socket(ws: WebSocket) -> None:
        host = ws.headers.get("host")
        origin = ws.headers.get("origin")
        if not is_allowed_host(host, allowed_hosts) or not is_same_origin(origin, host):
            log.warning("Refused WebSocket from origin %r to host %r", origin, host)
            await ws.close(code=1008)  # policy violation
            return
        user = auth.active_user(ws)  # the session cookie comes with the handshake
        if user is None:
            await ws.close(code=4401)  # not logged in (or trial over)
            return
        await ws.accept()
        logger = SessionLogger(db_path, owner=user.id)
        session = PostureSession(settings, baselines.get(user.id))
        last_alert_id: int | None = None
        label_counts = {"correct": 0, "false_alarm": 0, "missed": 0}
        alerts_today = logger.alerts_today()
        # A recorded session covers only time with frames arriving: it starts at the first
        # frame, ends at the last one, and a long gap (camera stopped) splits it, so an
        # open tab with the camera off never counts as monitoring time.
        idle_gap = max(60.0, 3 * float(settings["away_timeout_seconds"]))
        rec = {"on": False, "pose_ms": 0.0, "frames": 0, "last_mono": 0.0, "last_wall": None}

        def stop_recording() -> None:
            if rec["on"]:
                avg = rec["pose_ms"] / rec["frames"] if rec["frames"] else None
                logger.end_session(avg_cpu=None, avg_latency_ms=avg, ts=rec["last_wall"])
                live_sessions.discard(logger.session_id)
                log.info("Web session %s ended (account %s)", logger.session_id, user.id)
            rec.update(on=False, pose_ms=0.0, frames=0)

        def start_recording() -> None:
            logger.start_session()
            live_sessions.add(logger.session_id)
            rec["on"] = True
            log.info("Web session %s started (account %s)", logger.session_id, user.id)

        async def error(message: str) -> None:
            await ws.send_json({"type": "error", "message": message})

        await ws.send_json({"type": "hello", "config": config(),
                            "calibrated": session.baseline is not None,
                            "alerts_today": alerts_today, "username": user.username})
        try:
            while True:
                incoming = await ws.receive()
                if incoming["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(incoming.get("code", 1000))
                text = incoming.get("text")
                if text is None:
                    await error("Send JSON text messages")
                    continue
                try:
                    raw = json.loads(text)
                except ValueError:
                    await error("Message is not valid JSON")
                    continue
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
                    now_mono = clock()
                    if rec["on"] and now_mono - rec["last_mono"] > idle_gap:
                        stop_recording()  # the camera was off for a while
                        session.set_baseline(session.baseline)  # fresh smoothing and state
                    if not rec["on"]:
                        start_recording()
                    rec["last_mono"] = now_mono
                    rec["last_wall"] = datetime.now()
                    if msg.pose_ms is not None:
                        rec["pose_ms"] += msg.pose_ms
                        rec["frames"] += 1
                    # A calibration made in another tab of the same account applies here too.
                    current = baselines.get(user.id)
                    if current is not session.baseline and not session.calibrating:
                        session.set_baseline(current)
                    result = session.handle_frame(landmarks, clock(), _now_iso())
                    if result.new_baseline is not None:
                        baselines.save(user.id, result.new_baseline)
                        log.info("Calibration saved for account %s", user.id)
                    event_id = (logger.log_event(result.event, result.score)
                                if result.event else None)
                    alert = None
                    if result.alert:
                        last_alert_id = event_id
                        alerts_today = logger.alerts_today()
                        alert = {"title": notifier.title, "message": notifier.next_message()}
                    await ws.send_json(frame_payload(
                        result, alert, session.baseline is not None, alerts_today))

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
                    if logger.session_id is None:
                        await error("Start the camera first")
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
            stop_recording()  # CPU isn't recorded: it's the browser's, not ours
            logger.close()

    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
