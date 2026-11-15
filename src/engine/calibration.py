"""Average features over N seconds into a Baseline.  Phase 2.  Pure logic."""
from src.schemas.models import Baseline


def build_baseline(samples: list[dict]) -> Baseline:
    raise NotImplementedError
