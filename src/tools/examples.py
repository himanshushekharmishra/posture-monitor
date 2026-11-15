"""Save/load landmark example files (data/examples/*.json).

Only the 33 landmark coordinates are stored, never the camera image.

File format:
{
  "description": "...",
  "source": "synthetic" | "recorded",
  "expected": "good" | "slouch" | null,   # null = not labelled yet (tests skip it)
  "baseline": "upright.json",             # example to calibrate against
  "landmarks": [{"x": 0.5, "y": 0.3, "visibility": 0.99}, ...]   # 33 items
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.schemas.models import Point

LABELS = ("good", "slouch")


def landmarks_to_json(landmarks: list[Point]) -> list[dict[str, float]]:
    return [
        {"x": round(p.x, 5), "y": round(p.y, 5), "visibility": round(p.visibility, 4)}
        for p in landmarks
    ]


def dump_example(data: dict) -> str:
    """JSON with one landmark per line, so files stay short and diff well."""
    head = {k: v for k, v in data.items() if k != "landmarks"}
    body = ",\n".join(f"  {json.dumps(p)}" for p in data["landmarks"])
    text = json.dumps(head, indent=1)[:-2]  # drop the closing "\n}"
    return f'{text},\n "landmarks": [\n{body}\n ]\n}}\n'


def landmarks_from_json(items: list[dict]) -> list[Point]:
    return [Point(float(d["x"]), float(d["y"]), float(d.get("visibility", 1.0))) for d in items]


def load_example(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if len(data["landmarks"]) != 33:
        raise ValueError(f"{path.name}: expected 33 landmarks, got {len(data['landmarks'])}")
    if data.get("expected") not in (*LABELS, None):
        raise ValueError(f"{path.name}: expected must be one of {LABELS} or null")
    data["points"] = landmarks_from_json(data["landmarks"])
    return data


def save_example(
    folder: Path,
    landmarks: list[Point],
    description: str = "Recorded from the debug window",
    expected: str | None = None,
    baseline: str = "upright.json",
    name: str | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if name:
        path = folder / name
    else:  # never overwrite: two presses within a second get different names
        stem = f"recorded_{datetime.now():%Y%m%d_%H%M%S}"
        path, n = folder / f"{stem}.json", 2
        while path.exists():
            path, n = folder / f"{stem}_{n}.json", n + 1
    data = {
        "description": description,
        "source": "recorded",
        "expected": expected,
        "baseline": baseline,
        "landmarks": landmarks_to_json(landmarks),
    }
    path.write_text(dump_example(data), encoding="utf-8")
    return path
