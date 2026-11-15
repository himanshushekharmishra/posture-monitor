"""SQLite session/event logger.  Phase 4.

CREATE TABLE sessions (id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT,
                       avg_cpu REAL, avg_latency_ms REAL, user_id INTEGER);
CREATE TABLE events (id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
                     ts TEXT, type TEXT CHECK(type IN ('slouch_start','alert','recovered','away')),
                     score REAL);

CREATE TABLE labels (id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
                     event_id INTEGER REFERENCES events(id), ts TEXT,
                     kind TEXT CHECK(kind IN ('correct','false_alarm','missed')));

`labels` is filled only in --label sessions: the user marks each alert as correct
or a false alarm, and reports slouches that got no alert as missed.

Timestamps are local time in ISO 8601 with offset, so the first 10 characters are
the local date. Only events and summary numbers are stored, never images.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT,
    avg_cpu REAL, avg_latency_ms REAL, user_id INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
    ts TEXT, type TEXT CHECK(type IN ('slouch_start','alert','recovered','away')),
    score REAL
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
    event_id INTEGER REFERENCES events(id), ts TEXT,
    kind TEXT CHECK(kind IN ('correct','false_alarm','missed'))
);
"""


@dataclass(frozen=True)
class LabelSummary:
    correct: int
    false_alarm: int
    missed: int
    sessions: int
    minutes: float  # total length of the labelled sessions

    @property
    def labelled_alerts(self) -> int:
        return self.correct + self.false_alarm

    @property
    def precision(self) -> float | None:
        return self.correct / self.labelled_alerts if self.labelled_alerts else None

# State machine event name -> events.type. Others (e.g. "returned") aren't stored.
EVENT_TYPES = {
    "slouch_started": "slouch_start",
    "alerted": "alert",
    "recovered": "recovered",
    "away": "away",
}


def _now_iso(ts: datetime | None = None) -> str:
    return (ts or datetime.now()).astimezone().isoformat(timespec="seconds")


class SessionLogger:
    """One monitoring session per instance. Safe to query from another thread."""

    def __init__(self, db_path: Path, owner: int | None = None) -> None:
        """`owner` is a web account id; None means the desktop app. Every write and
        query is limited to that owner's sessions, so accounts never see each other's."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self.owner = owner
        self.session_id: int | None = None
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)")}
            if "user_id" not in cols:  # databases from before web accounts
                self._conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")

    def start_session(self, ts: datetime | None = None) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO sessions (started_at, user_id) VALUES (?, ?)",
                (_now_iso(ts), self.owner),
            )
        self.session_id = int(cur.lastrowid)
        return self.session_id

    def log_event(
        self, event: str, score: float | None, ts: datetime | None = None
    ) -> int | None:
        """Store a state machine event. Returns its row id, or None if it isn't stored."""
        kind = EVENT_TYPES.get(event)
        if kind is None:
            return None
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (session_id, ts, type, score) VALUES (?, ?, ?, ?)",
                (self.session_id, _now_iso(ts), kind, score),
            )
        return int(cur.lastrowid)

    def label(self, kind: str, event_id: int | None = None, ts: datetime | None = None) -> None:
        """kind: 'correct' / 'false_alarm' (with the alert's event_id) or 'missed'."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO labels (session_id, event_id, ts, kind) VALUES (?, ?, ?, ?)",
                (self.session_id, event_id, _now_iso(ts), kind),
            )

    def label_summary(self, session_id: int | None = None) -> LabelSummary:
        """Totals over this owner's labelled sessions, or just one session."""
        where = "JOIN sessions s ON s.id = l.session_id WHERE s.user_id IS ?"
        args: tuple = (self.owner,)
        if session_id:
            where += " AND l.session_id = ?"
            args += (session_id,)
        with self._lock:
            counts = dict(self._conn.execute(
                f"SELECT kind, COUNT(*) FROM labels l {where} GROUP BY kind", args
            ).fetchall())
            rows = self._conn.execute(
                "SELECT started_at, ended_at FROM sessions WHERE id IN "
                f"(SELECT DISTINCT l.session_id FROM labels l {where})", args
            ).fetchall()
        minutes = sum(
            (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60
            for start, end in rows if start and end
        )
        return LabelSummary(
            correct=counts.get("correct", 0),
            false_alarm=counts.get("false_alarm", 0),
            missed=counts.get("missed", 0),
            sessions=len(rows),
            minutes=minutes,
        )

    def end_session(
        self, avg_cpu: float | None, avg_latency_ms: float | None, ts: datetime | None = None
    ) -> None:
        if self.session_id is None:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ?, avg_cpu = ?, avg_latency_ms = ? WHERE id = ?",
                (_now_iso(ts), avg_cpu, avg_latency_ms, self.session_id),
            )

    def count_events(self, kind: str, day: date | None = None) -> int:
        day_str = (day or datetime.now().astimezone().date()).isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM events e JOIN sessions s ON s.id = e.session_id "
                "WHERE e.type = ? AND substr(e.ts, 1, 10) = ? AND s.user_id IS ?",
                (kind, day_str, self.owner),
            ).fetchone()
        return int(row[0])

    def recent_sessions(self, limit: int = 10) -> list[dict]:
        """Newest first, with event counts, for the web dashboard."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.id, s.started_at, s.ended_at, s.avg_cpu, s.avg_latency_ms,
                       SUM(e.type = 'alert'), SUM(e.type = 'slouch_start')
                FROM sessions s LEFT JOIN events e ON e.session_id = s.id
                WHERE s.user_id IS ?
                GROUP BY s.id ORDER BY s.id DESC LIMIT ?
                """,
                (self.owner, limit),
            ).fetchall()
        keys = ("id", "started_at", "ended_at", "avg_cpu", "avg_latency_ms", "alerts", "slouches")
        return [dict(zip(keys, (*r[:5], int(r[5] or 0), int(r[6] or 0)))) for r in rows]

    def alerts_today(self) -> int:
        return self.count_events("alert")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
