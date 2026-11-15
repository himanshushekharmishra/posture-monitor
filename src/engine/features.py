"""Landmarks -> PostureFeatures.  Phase 2.  Pure logic, no I/O."""
from src.schemas.models import Baseline, Point, PostureFeatures

NOSE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER = 0, 7, 8, 11, 12


def extract_features(landmarks: list[Point], baseline: Baseline | None) -> PostureFeatures:
    raise NotImplementedError


def deviation_score(f: PostureFeatures, baseline: Baseline, settings: dict) -> float:
    raise NotImplementedError
