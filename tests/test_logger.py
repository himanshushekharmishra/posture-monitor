import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from src.tools.logger import SessionLogger


def test_session_and_events_are_stored(tmp_path):
    db = tmp_path / "out" / "posture.db"
    lg = SessionLogger(db)
    sid = lg.start_session()
    assert lg.log_event("slouch_started", 0.4)
    assert lg.log_event("alerted", 0.5)
    assert lg.log_event("recovered", 0.1)
    assert lg.log_event("away", None)
    assert not lg.log_event("returned", 0.0)  # not part of the events schema
    lg.end_session(avg_cpu=4.2, avg_latency_ms=12.5)
    lg.close()

    conn = sqlite3.connect(db)
    types = [r[0] for r in conn.execute("SELECT type FROM events WHERE session_id = ? ORDER BY id", (sid,))]
    assert types == ["slouch_start", "alert", "recovered", "away"]
    started, ended, cpu, lat = conn.execute(
        "SELECT started_at, ended_at, avg_cpu, avg_latency_ms FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert started and ended and cpu == 4.2 and lat == 12.5
    conn.close()


def test_alerts_today_ignores_other_days_and_types(tmp_path):
    lg = SessionLogger(tmp_path / "p.db")
    lg.start_session()
    yesterday = datetime.now() - timedelta(days=1)
    lg.log_event("alerted", 0.5, ts=yesterday)
    lg.log_event("alerted", 0.5)
    lg.log_event("alerted", 0.6)
    lg.log_event("slouch_started", 0.3)
    assert lg.alerts_today() == 2
    assert lg.count_events("alert", yesterday.astimezone().date()) == 1
    lg.close()


def test_reopening_keeps_history(tmp_path):
    db = tmp_path / "p.db"
    a = SessionLogger(db)
    a.start_session()
    a.log_event("alerted", 0.5)
    a.close()
    b = SessionLogger(db)
    assert b.alerts_today() == 1
    assert b.start_session() == 2
    b.close()


def test_labels_and_precision_summary(tmp_path):
    lg = SessionLogger(tmp_path / "p.db")
    start = datetime(2026, 1, 1, 9, 0)
    sid = lg.start_session(ts=start)
    a1 = lg.log_event("alerted", 0.5)
    a2 = lg.log_event("alerted", 0.4)
    a3 = lg.log_event("alerted", 0.3)
    assert isinstance(a1, int) and a1 != a2
    lg.label("correct", a1)
    lg.label("correct", a2)
    lg.label("false_alarm", a3)
    lg.label("missed")
    lg.end_session(1.0, 12.0, ts=start + timedelta(minutes=30))
    s = lg.label_summary()
    assert (s.correct, s.false_alarm, s.missed, s.sessions) == (2, 1, 1, 1)
    assert s.precision == 2 / 3 and s.minutes == 30
    assert lg.label_summary(sid) == s
    lg.start_session()  # an unlabelled session doesn't count
    assert lg.label_summary().sessions == 1
    lg.close()


def test_empty_label_summary(tmp_path):
    lg = SessionLogger(tmp_path / "p.db")
    s = lg.label_summary()
    assert s.labelled_alerts == 0 and s.precision is None and s.minutes == 0
    lg.close()


def test_baseline_watcher(tmp_path):
    from src.engine.calibration import build_baseline
    from src.engine.features import measure
    from src.tools.baseline_store import BaselineWatcher, save_baseline
    from src.tools.examples import load_example

    pts = load_example(Path(__file__).parent.parent / "data/examples/upright.json")["points"]
    b = build_baseline([measure(pts)], "t")
    path = tmp_path / "baseline.json"
    clock = {"t": 0.0}
    w = BaselineWatcher(path, check_every=2, clock=lambda: clock["t"])
    assert w.poll() == (False, None)
    save_baseline(b, path)
    assert w.poll() == (False, None)  # not time to check yet
    clock["t"] = 2.5
    changed, loaded = w.poll()
    assert changed and loaded == b
    clock["t"] = 5
    assert w.poll() == (False, None)  # unchanged
    save_baseline(b, path)
    w.mark_current()  # our own write
    clock["t"] = 8
    assert w.poll() == (False, None)
    path.unlink()
    clock["t"] = 11
    assert w.poll() == (True, None)  # deleted
