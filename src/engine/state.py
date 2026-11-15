"""EMA smoothing + posture state machine.  Phase 3.  Pure logic.

Time is passed in (seconds, float) so tests can simulate it.
"""
from src.schemas.models import PostureState


class Ema:
    def __init__(self, alpha: float) -> None:
        raise NotImplementedError


class PostureStateMachine:
    """AWAY | GOOD | SLOUCHING | ALERTED with persistence and cooldown."""

    def update(self, score: float | None, now: float) -> tuple[PostureState, bool]:
        """Returns (new_state, should_alert)."""
        raise NotImplementedError
