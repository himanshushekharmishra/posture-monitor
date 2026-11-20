"""Every settings["key"] the code reads must exist in config/settings.json."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_RE = re.compile(r"""settings\[["']([a-z_]+)["']\]""")


def test_all_settings_keys_exist():
    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "backend").rglob("*.py"),
             *(ROOT / "scripts").glob("*.py")]
    used = {k for f in files for k in KEY_RE.findall(f.read_text(encoding="utf-8"))}
    assert used, "no settings keys found; regex out of date?"
    missing = sorted(used - settings.keys())
    assert missing == []


def test_weights_sum_to_one():
    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    assert abs(sum(settings["weights"].values()) - 1.0) < 1e-9


def test_shipped_settings_are_valid():
    from src.utils.validate import settings_problems

    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    assert settings_problems(settings) == []


def test_bad_settings_are_all_reported():
    from src.utils.validate import settings_problems

    s = json.loads((ROOT / "config" / "settings.json").read_text())
    s.update(process_fps=0, ema_alpha=5, min_visibility=1.5, camera_index=0.5,
             recovery_margin=0.3, web_port=70000, calibration_max_tilt_degrees=-1,
             web_dismiss_seconds=0)
    s["weights"] = {"neck": 0, "lean": 0, "shoulder_tilt": 0, "head_tilt": 0}
    del s["persist_seconds"]
    text = "\n".join(settings_problems(s))
    for key in ("process_fps", "ema_alpha", "min_visibility", "camera_index",
                "recovery_margin", "web_port", "calibration_max_tilt_degrees",
                "web_dismiss_seconds", "weights", "persist_seconds is missing"):
        assert key in text


def test_read_settings_rejects_bad_override(monkeypatch):
    import pytest

    from src.main import SettingsError, read_settings

    monkeypatch.setenv("PROCESS_FPS", "0")
    with pytest.raises(SettingsError, match="process_fps"):
        read_settings()
    monkeypatch.setenv("PROCESS_FPS", "fast")
    with pytest.raises(SettingsError, match="PROCESS_FPS"):
        read_settings()
