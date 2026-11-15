"""Fill a demo database with two weeks of made-up sessions, for README screenshots.

Never point this at your real posture.db: it adds fake sessions to the account.

    1. Start a demo server on its own database (PowerShell):
         $env:DB_PATH = "data/output/demo.db"
         $env:SECRET_KEY_PATH = "data/output/demo-secret.key"
         python -m backend --port 8001
    2. Sign up as a guest at http://127.0.0.1:8001 with any username.
    3. python scripts\\make_demo_data.py --user <that username>

Defaults to data/output/demo.db (gitignored). Same seed, same data.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tools.logger import SessionLogger  # noqa: E402

DAYS = 14
SLOUCH_MINUTES = [0.2, 0.3, 0.4, 0.4, 0.8, 1.5, 3]  # how long each made-up slouch lasts
ALERT_AFTER_MINUTES = 0.5                             # matches persist_seconds = 30


def user_id(db: Path, username: str) -> int:
    if not db.is_file():
        raise SystemExit(f"{db} doesn't exist. Start the demo server and sign up first.")
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if row is None:
        raise SystemExit(f"No account '{username}' in {db}. Sign up on the demo server first.")
    return int(row[0])


def seed(db: Path, owner: int, seed_value: int = 7) -> int:
    rnd = random.Random(seed_value)
    now = datetime.now().astimezone().replace(second=0, microsecond=0)
    today = now.replace(hour=0, minute=0)
    log = SessionLogger(db, owner=owner)
    sessions = 0
    for days_ago in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        weekend = day.weekday() >= 5
        starts = [10, 14] if weekend else [9, 13, 16]
        if weekend and rnd.random() < 0.5:
            starts = [11]
        for hour in starts:
            start = day + timedelta(hours=hour, minutes=rnd.randint(0, 40))
            end = start + timedelta(minutes=rnd.randint(45, 130))
            if end > now:
                continue
            log.start_session(start)
            # Afternoons are worse, and posture gets a little better over the two weeks.
            chance = (0.24 if hour >= 13 else 0.11) * (1 - 0.35 * (DAYS - 1 - days_ago) / (DAYS - 1))
            t = start + timedelta(minutes=rnd.randint(3, 10))
            while t < end - timedelta(minutes=3):
                if rnd.random() < chance:
                    log.log_event("slouch_started", 0.32, t)
                    minutes = rnd.choice(SLOUCH_MINUTES)
                    if minutes >= ALERT_AFTER_MINUTES:
                        log.log_event("alerted", 0.41, t + timedelta(minutes=ALERT_AFTER_MINUTES))
                    t += timedelta(minutes=minutes)
                    log.log_event("recovered", 0.12, t)
                t += timedelta(minutes=5)
            log.end_session(0.5, round(rnd.uniform(10, 15), 1), end)
            sessions += 1
    return sessions


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user", required=True, help="username of the demo account")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "output" / "demo.db")
    args = p.parse_args()
    if args.db.name == "posture.db":
        raise SystemExit("Refusing to add fake sessions to posture.db; use a demo database.")
    n = seed(args.db, user_id(args.db, args.user))
    print(f"Added {n} sessions for '{args.user}' to {args.db}")


if __name__ == "__main__":
    main()
