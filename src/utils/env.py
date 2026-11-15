"""Override settings from a .env file or environment variables.  Pure functions.

A variable overrides the top-level setting with the same name in lower case:
CAMERA_INDEX=1 sets settings["camera_index"] = 1. Values are converted to the
type the setting already has (int, float, bool or str). Unknown names and nested
settings (like "weights") are ignored.
"""
from __future__ import annotations

from collections.abc import Mapping

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Ignores blanks, comments and `export ` prefixes."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        out[key.strip()] = value
    return out


def _convert(current: object, value: str, key: str) -> object:
    if isinstance(current, bool):
        v = value.lower()
        if v in TRUE:
            return True
        if v in FALSE:
            return False
        raise ValueError(f"{key}: expected true/false, got {value!r}")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def apply_overrides(settings: dict, *sources: Mapping[str, str]) -> tuple[dict, list[str]]:
    """Return (new settings, names applied). Later sources win over earlier ones."""
    merged: dict[str, str] = {}
    for src in sources:
        merged.update({k.upper(): v for k, v in src.items()})
    result = dict(settings)
    applied: list[str] = []
    for key, current in settings.items():
        name = key.upper()
        if name in merged and not isinstance(current, (dict, list)):
            try:
                result[key] = _convert(current, merged[name], name)
            except ValueError as e:
                raise ValueError(f"Bad override {name}={merged[name]!r}: {e}") from e
            applied.append(name)
    return result, applied
