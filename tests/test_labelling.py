import importlib.util
import sys
from pathlib import Path

from src.tools.logger import LabelSummary
from src.workflows.monitor_loop import AlertLabeller

ROOT = Path(__file__).resolve().parent.parent


def load_benchmark():
    spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmark"] = mod  # dataclasses look the module up while it loads
    spec.loader.exec_module(mod)
    return mod


def test_yes_no_only_answer_a_pending_alert():
    lab = AlertLabeller()
    assert lab.handle_key(ord("y")) is None  # nothing to answer yet
    lab.alert_fired(7)
    assert any("ALERT" in line for line in lab.overlay_lines())
    assert lab.handle_key(ord("y")) == ("correct", 7)
    assert lab.handle_key(ord("n")) is None  # already answered
    lab.alert_fired(8)
    assert lab.handle_key(ord("n")) == ("false_alarm", 8)
    assert not any("ALERT" in line for line in lab.overlay_lines())


def test_missed_works_any_time_and_other_keys_are_ignored():
    lab = AlertLabeller()
    assert lab.handle_key(ord("m")) == ("missed", None)
    assert lab.handle_key(ord("x")) is None
    assert lab.handle_key(255) is None  # cv2.waitKey with no key pressed
    assert lab.counts == {"correct": 0, "false_alarm": 0, "missed": 1}


def test_precision_text():
    bench = load_benchmark()
    assert "not measured" in bench.precision_text(None)
    assert "missed" in bench.precision_text(LabelSummary(0, 0, 2, 1, 10))
    full = bench.precision_text(LabelSummary(9, 1, 2, 1, 35))
    assert full.startswith("90% (9 of 10 alerts right, 2 missed") and "preliminary" not in full
    assert "preliminary" in bench.precision_text(LabelSummary(3, 1, 0, 1, 12))
