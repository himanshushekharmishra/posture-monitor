"""Read one account's sessions and events from posture.db (read-only queries).

Every query is limited to the owner's sessions, so an id from another account is
treated exactly like one that doesn't exist.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.insights import Event, SessionRow


class History:
    def __init__(self, db_path: Path, owner: int) -> None:
        self.owner = owner
        self._conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self._ready = {"sessions", "events"} <= tables

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> History:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def sessions(self, limit: int | None = None, before_id: int | None = None) -> list[SessionRow]:
        """Newest first."""
        if not self._ready:
            return []
        sql = ("SELECT id, started_at, ended_at, avg_latency_ms FROM sessions "
               "WHERE user_id IS ?")
        args: list = [self.owner]
        if before_id is not None:
            sql += " AND id < ?"
            args.append(before_id)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [SessionRow(*r) for r in self._conn.execute(sql, args)]

    def session(self, session_id: int) -> SessionRow | None:
        if not self._ready:
            return None
        r = self._conn.execute(
            "SELECT id, started_at, ended_at, avg_latency_ms FROM sessions "
            "WHERE id = ? AND user_id IS ?", (session_id, self.owner)).fetchone()
        return SessionRow(*r) if r else None

    def events(self, session_ids: list[int] | None = None) -> list[Event]:
        """Events in time order, for the given sessions or all of the owner's."""
        if not self._ready:
            return []
        sql = ("SELECT e.session_id, e.ts, e.type FROM events e "
               "JOIN sessions s ON s.id = e.session_id WHERE s.user_id IS ?")
        args: list = [self.owner]
        if session_ids is not None:
            if not session_ids:
                return []
            sql += f" AND e.session_id IN ({','.join('?' * len(session_ids))})"
            args += session_ids
        sql += " ORDER BY e.ts, e.id"
        return [Event(*r) for r in self._conn.execute(sql, args)]
