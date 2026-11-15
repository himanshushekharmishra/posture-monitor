"""Web backend: pure session logic and the real FastAPI app (REST + WebSocket)."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.session import CalibrationPhase, PostureSession, parse_landmarks
from src.schemas.models import PostureState as S
from src.tools.examples import load_example

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
EXAMPLES = ROOT / "data" / "examples"
UPRIGHT = load_example(EXAMPLES / "upright.json")
FORWARD = load_example(EXAMPLES / "head_forward.json")
FPS = SETTINGS["process_fps"]
CAL_SECONDS = SETTINGS["calibration_countdown_seconds"] + SETTINGS["calibration_seconds"]


def as_wire(example):
    return example["landmarks"] and [[d["x"], d["y"], d["visibility"]] for d in example["landmarks"]]


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------- session.py (pure) ----------

def feed(session, points, start, seconds):
    results, t = [], start
    for _ in range(int(seconds * FPS)):
        results.append(session.handle_frame(points, t, "2026-01-01T00:00:00+00:00"))
        t += 1 / FPS
    return results, t


def test_session_calibrates_then_scores():
    s = PostureSession(SETTINGS, baseline=None)
    r, t = feed(s, UPRIGHT["points"], 0, 1)
    assert r[-1].note == "not calibrated" and r[-1].score is None
    s.start_calibration(t)
    r, t = feed(s, UPRIGHT["points"], t, CAL_SECONDS + 1)
    phases = [x.calibration.phase for x in r if x.calibration]
    assert phases[0] == CalibrationPhase.COUNTDOWN and CalibrationPhase.RECORDING in phases
    done = [x for x in r if x.new_baseline is not None]
    assert len(done) == 1 and done[0].calibration.phase == CalibrationPhase.DONE
    assert not s.calibrating and s.baseline is not None
    r, _ = feed(s, UPRIGHT["points"], t, 2)
    assert r[-1].state == S.GOOD and r[-1].score == pytest.approx(0, abs=1e-6)


def test_session_alerts_on_sustained_slouch():
    s = PostureSession(SETTINGS, baseline=None)
    s.start_calibration(0)
    _, t = feed(s, UPRIGHT["points"], 0, CAL_SECONDS + 1)
    r, _ = feed(s, FORWARD["points"], t, SETTINGS["persist_seconds"] + 3)
    alerts = [x for x in r if x.alert]
    assert len(alerts) == 1 and alerts[0].state == S.ALERTED
    assert r[0].features is not None
    assert r[0].features["neck_ratio"] < s.baseline.neck_ratio  # head dropped


def test_calibration_fails_without_a_person():
    s = PostureSession(SETTINGS, baseline=None)
    s.start_calibration(0)
    r, _ = feed(s, None, 0, CAL_SECONDS + 1)
    last = [x.calibration for x in r if x.calibration][-1]
    assert last.phase == CalibrationPhase.FAILED and "good frames" in last.message
    assert s.baseline is None and not s.calibrating


def test_parse_landmarks_validates():
    assert parse_landmarks(None) is None
    pts = parse_landmarks([[0.5, 0.5, 2.0]] * 33)
    assert len(pts) == 33 and pts[0].visibility == 1.0  # clamped
    with pytest.raises(ValueError, match="33"):
        parse_landmarks([[0.5, 0.5]] * 3)
    with pytest.raises(ValueError, match="finite"):
        parse_landmarks([[float("nan"), 0.5, 1]] * 33)


# ---------- app.py (FastAPI) ----------

@pytest.fixture
def web(tmp_path):
    (tmp_path / "messages").mkdir()
    shutil.copy(ROOT / "messages" / "alerts.json", tmp_path / "messages")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<h1>hi</h1>")
    clock = FakeClock()
    settings = dict(SETTINGS)
    settings["web_allowed_hosts"] = [*SETTINGS["web_allowed_hosts"], "testserver"]  # TestClient's host
    app = create_app(settings, tmp_path, clock=clock)
    with TestClient(app) as client:
        yield client, clock, tmp_path


def test_rest_endpoints(web):
    client, _, _ = web
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["process_fps"] == SETTINGS["process_fps"] and "db_path" not in cfg
    assert client.get("/api/baseline").status_code == 404
    stats = client.get("/api/stats").json()
    assert stats["alerts_today"] == 0 and stats["labels"]["precision"] is None
    assert client.get("/model/pose_landmarker.task").status_code == 404  # no model in tmp
    assert "hi" in client.get("/").text  # frontend is served


def test_websocket_calibrate_alert_label(web):
    client, clock, root = web
    up, fwd = as_wire(UPRIGHT), as_wire(FORWARD)

    def send_frames(ws, landmarks, seconds):
        out = []
        for _ in range(int(seconds * FPS)):
            ws.send_json({"type": "frame", "landmarks": landmarks, "pose_ms": 12.0})
            out.append(ws.receive_json())
            clock.t += 1 / FPS
        return out

    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["calibrated"] is False

        ws.send_json({"type": "label", "kind": "correct"})
        assert ws.receive_json()["type"] == "error"  # nothing to label yet

        ws.send_json({"type": "calibrate"})
        assert ws.receive_json()["phase"] == "countdown"
        msgs = send_frames(ws, up, CAL_SECONDS + 1)
        assert any(m["calibration"] and m["calibration"]["phase"] == "done" for m in msgs)
        assert msgs[-1]["calibrated"] is True
        assert (root / SETTINGS["baseline_path"]).is_file()
        assert client.get("/api/baseline").status_code == 200

        msgs = send_frames(ws, fwd, SETTINGS["persist_seconds"] + 3)
        alerts = [m for m in msgs if m["alert"]]
        assert len(alerts) == 1 and alerts[0]["state"] == "alerted"
        assert alerts[0]["alert"]["message"] and alerts[0]["alerts_today"] == 1

        ws.send_json({"type": "label", "kind": "correct"})
        labelled = ws.receive_json()
        assert labelled["type"] == "labelled" and labelled["counts"]["correct"] == 1

        ws.send_json({"type": "frame", "landmarks": [[0.5, 0.5]] * 3})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "nonsense"})
        assert ws.receive_json()["type"] == "error"

    stats = client.get("/api/stats").json()
    assert stats["alerts_today"] == 1 and stats["labels"]["correct"] == 1
    session = stats["recent_sessions"][0]
    assert session["alerts"] == 1 and session["avg_latency_ms"] == pytest.approx(12.0)
    assert session["ended_at"] is not None


# ---------- security.py ----------

def test_security_helpers():
    from backend.security import host_name, is_allowed_host, is_same_origin

    assert host_name("127.0.0.1:8000") == "127.0.0.1"
    assert host_name("[::1]:8000") == "::1" and host_name("localhost") == "localhost"
    allowed = ["127.0.0.1", "localhost", "::1"]
    assert is_allowed_host("LOCALHOST:8000", allowed) and is_allowed_host("[::1]:8000", allowed)
    assert not is_allowed_host("evil.example:8000", allowed) and not is_allowed_host(None, allowed)
    assert is_same_origin(None, "127.0.0.1:8000")  # non-browser client
    assert is_same_origin("http://127.0.0.1:8000", "127.0.0.1:8000")
    assert not is_same_origin("https://evil.example", "127.0.0.1:8000")
    assert not is_same_origin("http://127.0.0.1:9999", "127.0.0.1:8000")  # other local app
    assert not is_same_origin("null", "127.0.0.1:8000")  # sandboxed iframe / file://


def test_websocket_from_another_site_is_refused(web):
    from starlette.websockets import WebSocketDisconnect

    client, _, root = web
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_foreign_host_header_is_refused(web):
    client, _, _ = web
    assert client.get("/api/stats", headers={"host": "evil.example:8000"}).status_code == 400
    assert client.get("/api/stats").status_code == 200


def test_malformed_messages_get_an_error_and_keep_the_socket_open(web):
    client, _, _ = web
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("{not json")
        assert ws.receive_json() == {"type": "error", "message": "Message is not valid JSON"}
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json()["message"] == "Send JSON text messages"
        ws.send_json([1, 2, 3])
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "frame", "landmarks": None})  # still works afterwards
        assert ws.receive_json()["type"] == "frame"


def test_baseline_written_by_the_desktop_app_is_picked_up(web):
    from src.engine.calibration import build_baseline
    from src.engine.features import measure
    from src.tools.baseline_store import save_baseline

    client, clock, root = web
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["calibrated"] is False
        # The desktop app calibrates while the page is open.
        save_baseline(build_baseline([measure(UPRIGHT["points"])], "desktop"),
                      root / SETTINGS["baseline_path"])
        clock.t += 3  # past the watcher's check interval
        ws.send_json({"type": "frame", "landmarks": as_wire(UPRIGHT)})
        msg = ws.receive_json()
        assert msg["calibrated"] is True and msg["note"] == ""
