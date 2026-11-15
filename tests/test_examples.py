"""Score every labelled example in data/examples/ against its baseline example."""
import json
from pathlib import Path

import pytest

from src.engine.calibration import build_baseline
from src.engine.features import deviation_score, extract_features, measure
from src.tools.examples import load_example, save_example

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "data" / "examples"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
LABELLED = sorted(
    p for p in EXAMPLES.glob("*.json") if json.loads(p.read_text())["expected"] is not None
)


def test_examples_exist():
    assert len(LABELLED) >= 4
    labels = {load_example(p)["expected"] for p in LABELLED}
    assert labels == {"good", "slouch"}


@pytest.mark.parametrize("path", LABELLED, ids=lambda p: p.stem)
def test_example_scores_as_labelled(path):
    ex = load_example(path)
    base = load_example(EXAMPLES / ex["baseline"])
    baseline = build_baseline([measure(base["points"])], "example")
    f = extract_features(ex["points"], baseline)
    assert f.visibility >= SETTINGS["min_visibility"]
    score = deviation_score(f, baseline, SETTINGS)
    slouch = score >= SETTINGS["slouch_threshold"]
    assert slouch == (ex["expected"] == "slouch"), f"{path.name}: score {score:.3f}"


def test_save_and_load_round_trip(tmp_path):
    pts = load_example(EXAMPLES / "upright.json")["points"]
    path = save_example(tmp_path, pts, expected=None)
    again = load_example(path)
    assert again["source"] == "recorded" and again["expected"] is None
    flat = [c for p in again["points"] for c in (p.x, p.y)]
    assert flat == pytest.approx([c for p in pts for c in (p.x, p.y)], abs=1e-5)


def test_load_rejects_wrong_length(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"expected": None, "landmarks": [{"x": 0, "y": 0}] * 5}))
    with pytest.raises(ValueError, match="33"):
        load_example(bad)


def test_quick_saves_do_not_overwrite(tmp_path):
    pts = load_example(EXAMPLES / "upright.json")["points"]
    paths = {save_example(tmp_path, pts) for _ in range(3)}
    assert len(paths) == 3 and all(p.is_file() for p in paths)
