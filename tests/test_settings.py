"""Every settings["key"] the code reads must exist in config/settings.json."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_RE = re.compile(r"""settings\[["']([a-z_]+)["']\]""")


def test_all_settings_keys_exist():
    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    files = [*(ROOT / "src").rglob("*.py"), ROOT / "scripts" / "benchmark.py"]
    used = {k for f in files for k in KEY_RE.findall(f.read_text(encoding="utf-8"))}
    assert used, "no settings keys found; regex out of date?"
    missing = sorted(used - settings.keys())
    assert missing == []


def test_weights_sum_to_one():
    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    assert abs(sum(settings["weights"].values()) - 1.0) < 1e-9
