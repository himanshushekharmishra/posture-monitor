"""EMA smoothing + posture state machine.  Phase 3.  Pure logic.

Time is passed in (seconds, float) so tests can simulate it.
"""
from __future__ import annotations

from src.schemas.models import PostureState


class Ema:
    """Exponential moving average. `alpha` is the weight of the newest value."""

    def __init__(self, alpha: float) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.alpha * x + (1 - self.alpha) * self.value
        return self.value

    def reset(self) -> None:
        self.value = None


class PostureStateMachine:
    """AWAY | GOOD | SLOUCHING | ALERTED with persistence and cooldown.

    - score None means no usable person this frame. After `away_timeout` seconds
      of that the state becomes AWAY; shorter gaps keep the current state.
    - score >= threshold starts SLOUCHING. If it lasts `persist_seconds`, the
      state becomes ALERTED and an alert fires, unless one fired less than
      `cooldown_seconds` ago. Still slouching after the cooldown alerts again.
    - Recovery needs score < threshold - recovery_margin (hysteresis), so a
      score hovering at the threshold doesn't flap between states.

    `event` names what happened on the latest update ("slouch_started",
    "alerted", "recovered", "away", "returned") or is None, for the logger.
    """

    def __init__(
        self,
        threshold: float,
        persist_seconds: float,
        cooldown_seconds: float,
        away_timeout: float,
        recovery_margin: float = 0.0,
    ) -> None:
        self.threshold = threshold
        self.recover_below = threshold - recovery_margin
        self.persist_seconds = persist_seconds
        self.cooldown_seconds = cooldown_seconds
        self.away_timeout = away_timeout
        self.state = PostureState.AWAY
        self.event: str | None = None
        self._last_seen: float | None = None
        self._slouch_start: float | None = None
        self._last_alert: float | None = None

    @classmethod
    def from_settings(cls, settings: dict) -> PostureStateMachine:
        return cls(
            threshold=float(settings["slouch_threshold"]),
            persist_seconds=float(settings["persist_seconds"]),
            cooldown_seconds=float(settings["cooldown_minutes"]) * 60.0,
            away_timeout=float(settings["away_timeout_seconds"]),
            recovery_margin=float(settings["recovery_margin"]),
        )

    def reset(self) -> None:
        """Back to AWAY (e.g. when paused). Keeps the cooldown so a pause can't skip it."""
        self.state = PostureState.AWAY
        self.event = None
        self._last_seen = None
        self._slouch_start = None

    def slouch_seconds(self, now: float) -> float:
        return 0.0 if self._slouch_start is None else now - self._slouch_start

    def _cooldown_over(self, now: float) -> bool:
        return self._last_alert is None or now - self._last_alert >= self.cooldown_seconds

    def update(self, score: float | None, now: float) -> tuple[PostureState, bool]:
        """Returns (new_state, should_alert)."""
        self.event = None
        if score is None:
            gone_long = self._last_seen is None or now - self._last_seen >= self.away_timeout
            if gone_long and self.state != PostureState.AWAY:
                self.state = PostureState.AWAY
                self._slouch_start = None
                self.event = "away"
            return self.state, False

        self._last_seen = now
        was_away = self.state == PostureState.AWAY
        slouching = self.state in (PostureState.SLOUCHING, PostureState.ALERTED)

        if score >= self.threshold or (slouching and score >= self.recover_below):
            if not slouching:
                self.state = PostureState.SLOUCHING
                self._slouch_start = now
                self.event = "slouch_started"
            if self.slouch_seconds(now) >= self.persist_seconds and self._cooldown_over(now):
                self.state = PostureState.ALERTED
                self._last_alert = now
                self.event = "alerted"
                return self.state, True
            return self.state, False

        if slouching:
            self.event = "recovered"
        elif was_away:
            self.event = "returned"
        self.state = PostureState.GOOD
        self._slouch_start = None
        return self.state, False
