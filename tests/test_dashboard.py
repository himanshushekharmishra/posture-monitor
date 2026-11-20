"""Dashboard: slouch maths, history endpoints, and account settings."""
import json
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth.store import AuthStore
from backend.insights import Event, SessionRow, build_insights, per_hour, summarize_session
from src.tools.logger import SessionLogger

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
PW = "correct horse battery"
TZ = "+05:30"
NOW = datetime.fromisoformat(f"2026-03-10T12:00:00{TZ}")


def ts(hhmm: str, day: str = "2026-03-10") -> str:
    return f"{day}T{hhmm}:00{TZ}"


# ---------- insights.py (pure) ----------

def test_slouch_time_is_measured_between_start_and_recovery():
    row = SessionRow(1, ts("09:00"), ts("10:00"), 12.0)
    events = [Event(1, ts("09:10"), "slouch_start"), Event(1, ts("09:10"), "alert"),
              Event(1, ts("09:15"), "recovered"), Event(1, ts("09:30"), "slouch_start"),
              Event(1, ts("09:40"), "away"), Event(1, ts("09:50"), "slouch_start")]
    s = summarize_session(row, events, NOW)
    assert (s.minutes, s.slouches, s.alerts) == (60, 3, 1)
    assert s.slouch_minutes == 5 + 10 + 10  # the last slouch runs to the session's end
    assert s.slouch_share == pytest.approx(25 / 60) and s.status == "ended"


def test_session_status_live_and_interrupted():
    open_row = SessionRow(2, ts("11:00"), None, None)
    live = summarize_session(open_row, [], NOW, frozenset({2}))
    assert live.status == "live" and live.minutes == 60
    dead = summarize_session(open_row, [Event(2, ts("11:20"), "slouch_start")], NOW)
    assert dead.status == "interrupted" and dead.minutes == 20 and dead.slouch_minutes == 0


def test_per_hour_and_insights():
    assert per_hour(3, 30) == 6.0 and per_hour(3, 0.5) is None
    rows = [summarize_session(SessionRow(1, ts("09:00", "2026-03-09"), ts("10:00", "2026-03-09"), None),
                              [Event(1, ts("09:05", "2026-03-09"), "slouch_start"),
                               Event(1, ts("09:06", "2026-03-09"), "recovered")], NOW),
            summarize_session(SessionRow(2, ts("14:00"), ts("14:30"), None),
                              [Event(2, ts("14:10"), "slouch_start")], NOW)]
    events = [Event(1, ts("09:05", "2026-03-09"), "slouch_start"), Event(2, ts("14:10"), "slouch_start")]
    out = build_insights(rows, events, date(2026, 3, 10), days=7)
    assert len(out["daily"]) == 7 and out["daily"][-1]["date"] == "2026-03-10"
    assert out["today"]["slouches"] == 1 and out["today"]["per_hour"] == 2.0
    assert out["by_hour"][9] == 1 and out["by_hour"][14] == 1
    assert out["totals"]["sessions"] == 2 and out["totals"]["hours"] == 1.5
    assert out["window"]["per_hour"] == pytest.approx(2 / 1.5, abs=0.01)


# ---------- endpoints ----------

@pytest.fixture
def env(tmp_path):
    (tmp_path / "messages").mkdir()
    shutil.copy(ROOT / "messages" / "alerts.json", tmp_path / "messages")
    settings = dict(SETTINGS)
    settings["web_allowed_hosts"] = [*SETTINGS["web_allowed_hosts"], "testserver"]
    db = tmp_path / settings["db_path"]
    store = AuthStore(db, secret=b"s" * 32)
    app = create_app(settings, tmp_path, auth_store=store)
    with TestClient(app) as client:
        yield client, db, store


def signup(client, username):
    r = client.post("/api/auth/signup", json={"username": username, "password": PW, "guest": True})
    assert r.status_code == 201
    return r.json()["id"]


def record_session(db, owner, slouches=2):
    lg = SessionLogger(db, owner=owner)
    lg.start_session()
    for _ in range(slouches):
        lg.log_event("slouch_started", 0.4)
        lg.log_event("recovered", 0.1)
    lg.end_session(None, 11.0)
    sid = lg.session_id
    lg.close()
    return sid


def test_sessions_pagination_and_privacy(env):
    client, db, _ = env
    me = signup(client, "pager")
    ids = [record_session(db, me) for _ in range(5)]
    page = client.get("/api/sessions?limit=2").json()
    assert [s["id"] for s in page["sessions"]] == ids[:-3:-1] and page["next_before"] == ids[-2]
    page2 = client.get(f"/api/sessions?limit=2&before={page['next_before']}").json()
    assert [s["id"] for s in page2["sessions"]] == [ids[2], ids[1]]
    detail = client.get(f"/api/sessions/{ids[0]}").json()
    assert detail["slouches"] == 2 and [e["type"] for e in detail["events"]][:2] == \
        ["slouch_start", "recovered"]

    client.post("/api/auth/logout", json={})
    signup(client, "snoop")
    assert client.get(f"/api/sessions/{ids[0]}").status_code == 404  # not yours = not found
    assert client.get("/api/sessions").json()["sessions"] == []
    assert client.get("/api/insights").json()["totals"]["sessions"] == 0


def test_insights_endpoint(env):
    client, db, _ = env
    me = signup(client, "meter")
    record_session(db, me, slouches=3)
    out = client.get("/api/insights?days=7").json()
    assert out["today"]["slouches"] == 3 and out["totals"]["slouches"] == 3
    assert len(out["daily"]) == 7 and sum(out["by_hour"]) == 3
    assert client.get("/api/insights?days=500").status_code == 422
    client.post("/api/auth/logout", json={})
    assert client.get("/api/insights").status_code == 401


def test_profile_update(env):
    client, *_ = env
    signup(client, "profiler")
    r = client.post("/api/account/profile", json={"display_name": "  Shubh  ", "email": "s@example.com"})
    assert r.status_code == 200 and r.json()["display_name"] == "Shubh"
    assert r.json()["email"] == "s@example.com" and r.json()["created_at"]
    bad = client.post("/api/account/profile", json={"display_name": "x", "email": "not-an-email"})
    assert bad.status_code == 400
    cleared = client.post("/api/account/profile", json={"display_name": "", "email": ""}).json()
    assert cleared["display_name"] is None and cleared["email"] is None


def test_password_change_logs_out_other_devices(env):
    client, db, store = env
    signup(client, "changer")
    other = TestClient(client.app)
    other.post("/api/auth/login", json={"username": "changer", "password": PW})
    assert other.get("/api/auth/me").status_code == 200

    wrong = client.post("/api/account/password",
                        json={"current_password": "not it at all", "new_password": "new long secret"})
    assert wrong.status_code == 403
    weak = client.post("/api/account/password",
                       json={"current_password": PW, "new_password": "short"})
    assert weak.status_code == 400
    ok = client.post("/api/account/password",
                     json={"current_password": PW, "new_password": "new long secret"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # this device stays logged in
    assert other.get("/api/auth/me").status_code == 401  # the other one is logged out
    client.post("/api/auth/logout", json={})
    assert client.post("/api/auth/login", json={"username": "changer", "password": PW}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "changer", "password": "new long secret"}).status_code == 200


def test_delete_account_removes_everything(env):
    client, db, store = env
    me = signup(client, "leaver")
    record_session(db, me)
    store.save_baseline_json(me, "{}")
    r = client.post("/api/account/delete", json={})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert store.get_user(me) is None and store.get_baseline_json(me) is None
    lg = SessionLogger(db, owner=me)
    assert lg.recent_sessions() == []
    lg.close()
    signup(client, "leaver")  # the name is free again


def test_delete_account_needs_a_login(env):
    client, _, _ = env
    assert client.post("/api/account/delete", json={}).status_code == 401


def test_web_sessions_only_count_time_with_frames(tmp_path):
    """An open tab with the camera off isn't monitoring time; a long gap splits sessions."""
    (tmp_path / "messages").mkdir()
    shutil.copy(ROOT / "messages" / "alerts.json", tmp_path / "messages")
    settings = dict(SETTINGS)
    settings["web_allowed_hosts"] = [*SETTINGS["web_allowed_hosts"], "testserver"]
    clock = {"t": 1000.0}
    app = create_app(settings, tmp_path, clock=lambda: clock["t"],
                     auth_store=AuthStore(tmp_path / settings["db_path"], secret=b"s" * 32))
    with TestClient(app) as client:
        signup(client, "framer")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            clock["t"] += 600  # ten minutes with the camera off
        assert client.get("/api/sessions").json()["sessions"] == []

        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            for _ in range(3):
                ws.send_json({"type": "frame", "landmarks": None})
                ws.receive_json()
                clock["t"] += 0.2
            live = client.get("/api/sessions").json()["sessions"]
            assert len(live) == 1 and live[0]["status"] == "live"
            clock["t"] += 300  # camera stopped for five minutes, then started again
            ws.send_json({"type": "frame", "landmarks": None})
            ws.receive_json()
        sessions = client.get("/api/sessions").json()["sessions"]
        assert len(sessions) == 2 and all(s["status"] == "ended" for s in sessions)
        assert all(s["minutes"] < 1 for s in sessions)  # neither counts the gap
