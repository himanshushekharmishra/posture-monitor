"""Regenerate the synthetic landmark examples in data/examples/.

Recorded examples (saved with the `s` key in the --debug window) are not touched.

    python scripts\\make_examples.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.engine.calibration import build_baseline  # noqa: E402
from src.engine.features import (  # noqa: E402
    deviation_components, deviation_score, extract_features, measure,
)
from src.schemas.models import Point  # noqa: E402
from src.tools.examples import dump_example, landmarks_to_json  # noqa: E402

S = json.loads((ROOT / "config" / "settings.json").read_text())
OUT = ROOT / "data" / "examples"

# Person facing the camera, seated ~60 cm away. Their left = image right.
UPRIGHT = {
 0: (0.500, 0.300, .999), 1: (0.520, 0.272, .998), 2: (0.534, 0.271, .998), 3: (0.548, 0.272, .997),
 4: (0.480, 0.272, .998), 5: (0.466, 0.271, .998), 6: (0.452, 0.272, .997),
 7: (0.578, 0.292, .99), 8: (0.422, 0.292, .99), 9: (0.521, 0.336, .998), 10: (0.479, 0.336, .998),
 11: (0.660, 0.500, .995), 12: (0.340, 0.500, .995), 13: (0.720, 0.720, .90), 14: (0.280, 0.720, .90),
 15: (0.640, 0.900, .62), 16: (0.360, 0.900, .62), 17: (0.630, 0.930, .55), 18: (0.370, 0.930, .55),
 19: (0.620, 0.925, .56), 20: (0.380, 0.925, .56), 21: (0.635, 0.915, .58), 22: (0.365, 0.915, .58),
 23: (0.605, 0.980, .35), 24: (0.395, 0.980, .35), 25: (0.610, 1.250, .03), 26: (0.390, 1.250, .03),
 27: (0.615, 1.520, .01), 28: (0.385, 1.520, .01), 29: (0.615, 1.560, .01), 30: (0.385, 1.560, .01),
 31: (0.630, 1.580, .01), 32: (0.370, 1.580, .01),
}
HEAD = range(0, 11)

def pose(shift=(0, 0), scale=1.0, center=(0.5, 0.6), head_dy=0.0, head_scale=1.0,
         left_shoulder_dy=0.0, roll_deg=0.0):
    pts = {}
    hc = (0.5, 0.29)
    for i, (x, y, v) in UPRIGHT.items():
        if i in HEAD:  # head moves down/forward and looks bigger when closer
            x, y = hc[0] + (x - hc[0]) * head_scale, hc[1] + (y - hc[1]) * head_scale + head_dy
            if roll_deg:
                a = math.radians(roll_deg); dx, dy = x - hc[0], y - (hc[1] + head_dy)
                x, y = hc[0] + dx * math.cos(a) - dy * math.sin(a), hc[1] + head_dy + dx * math.sin(a) + dy * math.cos(a)
        if i in (11, 13, 15, 17, 19, 21, 23):
            y += left_shoulder_dy
        x, y = center[0] + (x - center[0]) * scale + shift[0], center[1] + (y - center[1]) * scale + shift[1]
        pts[i] = Point(x, y, v)
    return [pts[i] for i in range(33)]

base_pts = pose()
baseline = build_baseline([measure(base_pts)], "synthetic")
EXAMPLES = [
 ("upright.json", "Sitting upright, facing the camera. Baseline for the other examples.", "good", base_pts),
 ("upright_shifted.json", "Same upright posture, sitting a little to the left and slightly closer.", "good",
  pose(shift=(-0.10, 0.01), scale=1.04)),
 ("shoulder_tilt.json", "Upright but leaning on one elbow (left shoulder ~9 deg lower). Tilt alone stays below the alert threshold.", "good",
  pose(left_shoulder_dy=0.05)),
 ("head_forward.json", "Head dropped forward toward the screen ('tech neck'), shoulders unchanged.", "slouch",
  pose(head_dy=0.12, head_scale=1.10)),
 ("leaning_in.json", "Whole upper body leaning in toward the screen with the head dropping.", "slouch",
  pose(scale=1.25, head_dy=0.09, head_scale=1.05)),
 ("slumped.json", "Slumped in the chair: head down, one shoulder lower, head rolled to the side.", "slouch",
  pose(head_dy=0.10, head_scale=1.05, left_shoulder_dy=0.03, roll_deg=8)),
]
for name, desc, expected, pts in EXAMPLES:
    f = extract_features(pts, baseline)
    score = deviation_score(f, baseline, S)
    parts = {k: round(v, 3) for k, v in deviation_components(f, baseline, S).items()}
    print(f"{name:22s} {expected:7s} score={score:.3f} {parts}")
    (OUT / name).write_text(dump_example({"description": desc, "source": "synthetic", "expected": expected,
        "baseline": "upright.json", "landmarks": landmarks_to_json(pts)}), encoding="utf-8")
