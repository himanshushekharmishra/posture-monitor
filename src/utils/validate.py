"""Check settings before the app uses them.  Pure function.

Bad values (often from a typo in .env) otherwise fail far from their cause, for
example PROCESS_FPS=0 as a division by zero inside the frame throttle, or
EMA_ALPHA=5 as a score that never settles. All problems are reported at once.
"""
from __future__ import annotations

import math

POSITIVE = (
    "process_fps", "frame_width", "frame_height", "calibration_seconds",
    "calibration_min_samples", "calibration_max_tilt_degrees", "tilt_norm_degrees",
    "slouch_threshold", "persist_seconds",
    "away_timeout_seconds", "notification_timeout_seconds", "camera_retry_seconds",
)
NON_NEGATIVE = ("camera_index", "calibration_countdown_seconds", "cooldown_minutes",
                "recovery_margin")
FRACTIONS = ("min_visibility",)  # 0..1
WEIGHT_KEYS = ("neck", "lean", "shoulder_tilt", "head_tilt")


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def settings_problems(s: dict) -> list[str]:
    """Human-readable problems with the settings; empty if they're fine."""
    problems: list[str] = []

    def check(key: str, ok: bool, rule: str) -> None:
        if key not in s:
            problems.append(f"{key} is missing")
        elif not ok:
            problems.append(f"{key} must be {rule} (got {s[key]!r})")

    for k in POSITIVE:
        check(k, _num(s.get(k)) and s.get(k, 0) > 0, "a number greater than 0")
    for k in NON_NEGATIVE:
        check(k, _num(s.get(k)) and s.get(k, -1) >= 0, "a number of 0 or more")
    for k in FRACTIONS:
        check(k, _num(s.get(k)) and 0 <= s.get(k, -1) <= 1, "between 0 and 1")
    check("ema_alpha", _num(s.get("ema_alpha")) and 0 < s.get("ema_alpha", 0) <= 1,
          "greater than 0 and at most 1")
    for k in ("camera_index", "calibration_min_samples", "frame_width", "frame_height"):
        if k in s and _num(s[k]) and int(s[k]) != s[k]:
            problems.append(f"{k} must be a whole number (got {s[k]!r})")
    if all(_num(s.get(k)) for k in ("recovery_margin", "slouch_threshold")):
        if s["recovery_margin"] >= s["slouch_threshold"]:
            problems.append("recovery_margin must be smaller than slouch_threshold")

    weights = s.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(WEIGHT_KEYS):
        problems.append(f"weights must have exactly the keys {', '.join(WEIGHT_KEYS)}")
    elif not all(_num(v) and v >= 0 for v in weights.values()) or sum(weights.values()) <= 0:
        problems.append("weights must be 0 or more and not all 0")

    if "web_port" in s and not (isinstance(s["web_port"], int) and 1 <= s["web_port"] <= 65535):
        problems.append(f"web_port must be a port number 1-65535 (got {s['web_port']!r})")

    # Web accounts (only checked when present, so older configs still load).
    for k in ("auth_session_days", "guest_trial_days", "otp_ttl_minutes"):
        if k in s and not (isinstance(s[k], int) and not isinstance(s[k], bool) and s[k] > 0):
            problems.append(f"{k} must be a whole number greater than 0 (got {s[k]!r})")
    url = s.get("web_public_url")
    if url is not None and not (isinstance(url, str) and url.startswith(("http://", "https://"))):
        problems.append(f"web_public_url must start with http:// or https:// (got {url!r})")
    if s.get("sms_provider", "off") not in ("console", "twilio", "off"):
        problems.append(f"sms_provider must be console, twilio or off (got {s['sms_provider']!r})")
    return problems
