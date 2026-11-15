"""Shared data types."""
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    visibility: float = 1.0


@dataclass(frozen=True)
class PostureFeatures:
    neck_ratio: float
    lean_ratio: float
    shoulder_tilt: float
    head_tilt: float
    visibility: float


@dataclass(frozen=True)
class Baseline:
    neck_ratio: float
    shoulder_width: float
    shoulder_tilt: float
    head_tilt: float
    recorded_at: str


class PostureState(str, Enum):
    AWAY = "away"
    GOOD = "good"
    SLOUCHING = "slouching"
    ALERTED = "alerted"
