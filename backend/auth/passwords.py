"""Password hashing and username/password rules.  Pure, standard library only.

Hashes use scrypt (memory-hard, in hashlib) with a random 16-byte salt per password
and are stored as  scrypt$n$r$p$salt_b64$hash_b64  so the cost can be raised later
without breaking old hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
KEY_LEN = 32
MIN_PASSWORD, MAX_PASSWORD = 10, 128
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")

# The most common leaked passwords that also pass the length rule.
COMMON_PASSWORDS = {
    "1234567890", "12345678910", "123456789a", "qwertyuiop", "1q2w3e4r5t",
    "password12", "password123", "password1234", "iloveyou12", "qwerty1234",
    "qwerty12345", "1234qwerty", "abcdefghij", "aaaaaaaaaa", "0123456789",
    "passw0rd123", "welcome123", "football123", "baseball123", "letmein123",
    "monkey12345", "dragon12345", "sunshine123", "princess123", "admin12345",
    "administrator", "qazwsxedcrfv", "1qaz2wsx3edc", "zaq12wsxcde3", "trustno1234",
}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                            p=SCRYPT_P, dklen=KEY_LEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected),
                                maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# Verified against when the username doesn't exist, so a wrong username takes as
# long as a wrong password and response time doesn't reveal which accounts exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.fullmatch(username or ""):
        return ("Username must be 3-32 characters: letters, numbers, dots, dashes or "
                "underscores, starting with a letter or number.")
    return None


def password_problem(password: str, username: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Password must be at most {MAX_PASSWORD} characters."
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        return "That password is too easy to guess. Try a few unrelated words."
    if username and username.lower() in lowered:
        return "Password can't contain your username."
    return None
