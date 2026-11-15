"""Accounts, linked identities, login sessions and one-time codes (SQLite).

Tokens (session cookies, pending sign-ups) are random 256-bit values; only their
SHA-256 is stored, so a copy of the database can't be used to log in. Phone codes
are stored as an HMAC with the server's secret key, because a 6-digit code's plain
hash could be brute-forced.
"""
from __future__ import annotations

import hashlib
import math
import hmac
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    email TEXT,
    phone TEXT,
    is_guest INTEGER NOT NULL DEFAULT 0,
    trial_expires_at TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
CREATE TABLE IF NOT EXISTS identities (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('google', 'github', 'phone')),
    subject TEXT NOT NULL,
    email TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(provider, subject)
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);
CREATE TABLE IF NOT EXISTS pending_identities (
    token_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    name TEXT,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS otp_codes (
    phone TEXT PRIMARY KEY,
    code_mac TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_baselines (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MAX_FAILED_LOGINS = 8
LOCK_MINUTES = 15
OTP_MAX_ATTEMPTS = 5


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str | None
    email: str | None
    phone: str | None
    is_guest: bool
    trial_expires_at: datetime | None
    created_at: datetime
    password_hash: str
    locked_until: datetime | None

    def trial_expired(self, now: datetime) -> bool:
        return self.is_guest and self.trial_expires_at is not None and now >= self.trial_expires_at

    def trial_days_left(self, now: datetime) -> int | None:
        """Whole days left, rounded up: a new 14-day trial shows 14, the last hours show 1."""
        if not self.is_guest or self.trial_expires_at is None:
            return None
        seconds = (self.trial_expires_at - now).total_seconds()
        return max(0, math.ceil(seconds / 86400))


@dataclass(frozen=True)
class PendingIdentity:
    provider: str
    subject: str
    email: str | None
    name: str | None


class AuthStore:
    def __init__(self, db_path: Path, secret: bytes,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._secret = secret
        self.now = now
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- users ----------
    _USER_COLS = ("id, username, display_name, email, phone, is_guest, trial_expires_at, "
                  "created_at, password_hash, locked_until")

    def _row_to_user(self, row: tuple | None) -> User | None:
        if row is None:
            return None
        return User(id=row[0], username=row[1], display_name=row[2], email=row[3],
                    phone=row[4], is_guest=bool(row[5]), trial_expires_at=_parse(row[6]),
                    created_at=_parse(row[7]), password_hash=row[8],
                    locked_until=_parse(row[9]))

    def get_user(self, user_id: int) -> User | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE username = ?", (username,)
            ).fetchone()
        return self._row_to_user(row)

    def create_user(self, username: str, password_hash: str, *, display_name: str | None = None,
                    email: str | None = None, phone: str | None = None,
                    guest_trial_days: int | None = None) -> User:
        """Raises ValueError if the username is taken (case-insensitive)."""
        now = self.now()
        trial = _iso(now + timedelta(days=guest_trial_days)) if guest_trial_days else None
        try:
            with self._lock, self._conn:
                cur = self._conn.execute(
                    "INSERT INTO users (username, password_hash, display_name, email, phone, "
                    "is_guest, trial_expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (username, password_hash, display_name, email, phone,
                     int(guest_trial_days is not None), trial, _iso(now)),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError("That username is taken.") from e
        user = self.get_user(int(cur.lastrowid))
        assert user is not None
        return user

    def record_failed_login(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET failed_logins = failed_logins + 1 WHERE id = ?", (user_id,))
            (count,) = self._conn.execute(
                "SELECT failed_logins FROM users WHERE id = ?", (user_id,)).fetchone()
            if count >= MAX_FAILED_LOGINS:
                self._conn.execute(
                    "UPDATE users SET locked_until = ?, failed_logins = 0 WHERE id = ?",
                    (_iso(self.now() + timedelta(minutes=LOCK_MINUTES)), user_id))

    def record_login(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = ? "
                "WHERE id = ?", (_iso(self.now()), user_id))

    def is_locked(self, user: User) -> bool:
        return user.locked_until is not None and self.now() < user.locked_until

    def end_guest_trial(self, user_id: int) -> None:
        """A guest who links a verified identity becomes a regular account."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET is_guest = 0, trial_expires_at = NULL WHERE id = ?", (user_id,))

    # ---------- identities ----------
    def find_identity_user(self, provider: str, subject: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM identities WHERE provider = ? AND subject = ?",
                (provider, subject)).fetchone()
        return self.get_user(row[0]) if row else None

    def link_identity(self, user_id: int, provider: str, subject: str,
                      email: str | None = None) -> None:
        """Raises ValueError if that identity already belongs to an account."""
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO identities (user_id, provider, subject, email, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, provider, subject, email, _iso(self.now())))
                if provider == "phone":
                    self._conn.execute("UPDATE users SET phone = ? WHERE id = ?",
                                       (subject, user_id))
                elif email:
                    self._conn.execute(
                        "UPDATE users SET email = COALESCE(email, ?) WHERE id = ?",
                        (email, user_id))
        except sqlite3.IntegrityError as e:
            raise ValueError("That account is already connected to another user.") from e

    def linked_providers(self, user_id: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider FROM identities WHERE user_id = ? ORDER BY provider",
                (user_id,)).fetchall()
        return [r[0] for r in rows]

    # ---------- login sessions ----------
    def create_session(self, user_id: int, ttl: timedelta, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = self.now()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (_iso(now),))
            self._conn.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at, "
                "user_agent) VALUES (?, ?, ?, ?, ?)",
                (_hash_token(token), user_id, _iso(now), _iso(now + ttl), user_agent[:200]))
        return token

    def session_user(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at FROM auth_sessions WHERE token_hash = ?",
                (_hash_token(token),)).fetchone()
        if row is None or _parse(row[1]) <= self.now():
            return None
        return self.get_user(row[0])

    def delete_session(self, token: str | None) -> None:
        if token:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?",
                                   (_hash_token(token),))

    # ---------- verified identity waiting for a username + password ----------
    def create_pending(self, p: PendingIdentity, ttl: timedelta) -> str:
        token = secrets.token_urlsafe(32)
        now = self.now()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM pending_identities WHERE expires_at < ?",
                               (_iso(now),))
            self._conn.execute(
                "INSERT INTO pending_identities (token_hash, provider, subject, email, name, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_hash_token(token), p.provider, p.subject, p.email, p.name,
                 _iso(now + ttl)))
        return token

    def get_pending(self, token: str | None) -> PendingIdentity | None:
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT provider, subject, email, name, expires_at FROM pending_identities "
                "WHERE token_hash = ?", (_hash_token(token),)).fetchone()
        if row is None or _parse(row[4]) <= self.now():
            return None
        return PendingIdentity(*row[:4])

    def delete_pending(self, token: str | None) -> None:
        if token:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM pending_identities WHERE token_hash = ?",
                                   (_hash_token(token),))

    # ---------- phone codes ----------
    def _code_mac(self, phone: str, code: str) -> str:
        return hmac.new(self._secret, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()

    def create_otp(self, phone: str, ttl: timedelta) -> str:
        """New 6-digit code for this phone; replaces any earlier one."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO otp_codes (phone, code_mac, expires_at, attempts) "
                "VALUES (?, ?, ?, 0)",
                (phone, self._code_mac(phone, code), _iso(self.now() + ttl)))
        return code

    def check_otp(self, phone: str, code: str) -> bool:
        """True once for the right, unexpired code. Wrong guesses are limited."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT code_mac, expires_at, attempts FROM otp_codes WHERE phone = ?",
                (phone,)).fetchone()
            if row is None:
                return False
            mac, expires, attempts = row
            if _parse(expires) <= self.now() or attempts >= OTP_MAX_ATTEMPTS:
                self._conn.execute("DELETE FROM otp_codes WHERE phone = ?", (phone,))
                return False
            if hmac.compare_digest(mac, self._code_mac(phone, code)):
                self._conn.execute("DELETE FROM otp_codes WHERE phone = ?", (phone,))
                return True
            self._conn.execute(
                "UPDATE otp_codes SET attempts = attempts + 1 WHERE phone = ?", (phone,))
            return False

    # ---------- per-user calibration ----------
    def get_baseline_json(self, user_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM user_baselines WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None

    def save_baseline_json(self, user_id: int, data: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_baselines (user_id, data, updated_at) "
                "VALUES (?, ?, ?)", (user_id, data, _iso(self.now())))


def load_or_create_secret(path: Path) -> bytes:
    """The server's secret key (for HMACs), created on first run and kept private."""
    if path.is_file():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data
