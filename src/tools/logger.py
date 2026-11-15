"""SQLite session/event logger.  Phase 4.

CREATE TABLE sessions (id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT,
                       avg_cpu REAL, avg_latency_ms REAL);
CREATE TABLE events (id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
                     ts TEXT, type TEXT CHECK(type IN ('slouch_start','alert','recovered','away')),
                     score REAL);
"""
