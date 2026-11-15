"""Turn logged sessions and events into dashboard numbers.  Pure: no SQL, no clock.

Events are what the state machine logged: slouch_start, alert, recovered, away.
A slouch lasts from its slouch_start to the next recovered or away event, or to
the end of the session. Timestamps are local ISO 8601 strings, so their first 10
characters are the local date and characters 11-13 the local hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Event:
    session_id: int
    ts: str
    type: str


@dataclass(frozen=True)
class SessionRow:
    id: int
    started_at: str
    ended_at: str | None
    avg_latency_ms: float | None


@dataclass
class SessionSummary:
    id: int
    started_at: str
    ended_at: str | None
    minutes: float
    slouches: int
    alerts: int
    slouch_minutes: float
    avg_latency_ms: float | None
    status: str  # "ended", "live" or "interrupted" (no end recorded, not running now)
    events: list[dict] = field(default_factory=list)

    @property
    def slouch_share(self) -> float | None:
        return self.slouch_minutes / self.minutes if self.minutes > 0 else None

    def as_dict(self, with_events: bool = False) -> dict:
        d = {
            "id": self.id, "started_at": self.started_at, "ended_at": self.ended_at,
            "minutes": round(self.minutes, 1), "slouches": self.slouches, "alerts": self.alerts,
            "slouch_minutes": round(self.slouch_minutes, 1),
            "slouch_share": None if self.slouch_share is None else round(self.slouch_share, 3),
            "avg_latency_ms": None if self.avg_latency_ms is None
            else round(self.avg_latency_ms, 1),
            "status": self.status,
        }
        if with_events:
            d["events"] = self.events
        return d


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def summarize_session(row: SessionRow, events: list[Event], now: datetime,
                      live_ids: frozenset[int] = frozenset()) -> SessionSummary:
    """Duration, slouch count/time and alerts for one session (events in time order)."""
    start = _t(row.started_at)
    if row.ended_at:
        end, status = _t(row.ended_at), "ended"
    elif row.id in live_ids:
        end, status = now, "live"
    else:
        # Closed without a clean stop (crash, killed): end at the last thing we saw.
        end = _t(events[-1].ts) if events else start
        status = "interrupted"
    slouches = alerts = 0
    slouch_seconds = 0.0
    open_since: datetime | None = None
    for e in events:
        t = _t(e.ts)
        if e.type == "slouch_start":
            slouches += 1
            if open_since is None:
                open_since = t
        elif e.type == "alert":
            alerts += 1
        elif e.type in ("recovered", "away") and open_since is not None:
            slouch_seconds += max(0.0, (t - open_since).total_seconds())
            open_since = None
    if open_since is not None:
        slouch_seconds += max(0.0, (end - open_since).total_seconds())
    minutes = max(0.0, (end - start).total_seconds() / 60)
    return SessionSummary(
        id=row.id, started_at=row.started_at, ended_at=row.ended_at, minutes=minutes,
        slouches=slouches, alerts=alerts, slouch_minutes=min(slouch_seconds / 60, minutes),
        avg_latency_ms=row.avg_latency_ms, status=status,
        events=[{"ts": e.ts, "type": e.type} for e in events],
    )


def per_hour(slouches: int, minutes: float) -> float | None:
    """Slouches per hour of monitoring; None under a minute of data."""
    return round(slouches / (minutes / 60), 2) if minutes >= 1 else None


def build_insights(summaries: list[SessionSummary], events: list[Event], today: date,
                   days: int) -> dict:
    """Daily series for the last `days` days, hour-of-day pattern, and totals."""
    first_day = today - timedelta(days=days - 1)
    daily = {first_day + timedelta(days=i): {"minutes": 0.0, "slouches": 0, "alerts": 0,
                                             "slouch_minutes": 0.0} for i in range(days)}
    for s in summaries:
        d = date.fromisoformat(s.started_at[:10])
        if d in daily:
            daily[d]["minutes"] += s.minutes
            daily[d]["slouches"] += s.slouches
            daily[d]["alerts"] += s.alerts
            daily[d]["slouch_minutes"] += s.slouch_minutes

    by_hour = [0] * 24
    for e in events:
        if e.type == "slouch_start" and date.fromisoformat(e.ts[:10]) >= first_day:
            by_hour[int(e.ts[11:13])] += 1

    def bucket(d: date, v: dict) -> dict:
        return {"date": d.isoformat(), "minutes": round(v["minutes"], 1),
                "slouches": v["slouches"], "alerts": v["alerts"],
                "slouch_minutes": round(v["slouch_minutes"], 1),
                "per_hour": per_hour(v["slouches"], v["minutes"])}

    series = [bucket(d, v) for d, v in sorted(daily.items())]
    window_minutes = sum(v["minutes"] for v in daily.values())
    window_slouches = sum(v["slouches"] for v in daily.values())
    total_minutes = sum(s.minutes for s in summaries)
    total_slouches = sum(s.slouches for s in summaries)
    return {
        "days": days,
        "today": series[-1],
        "window": {"minutes": round(window_minutes, 1), "slouches": window_slouches,
                   "per_hour": per_hour(window_slouches, window_minutes)},
        "daily": series,
        "by_hour": by_hour,
        "totals": {
            "sessions": len(summaries),
            "hours": round(total_minutes / 60, 1),
            "slouches": total_slouches,
            "alerts": sum(s.alerts for s in summaries),
            "slouch_minutes": round(sum(s.slouch_minutes for s in summaries), 1),
            "per_hour": per_hour(total_slouches, total_minutes),
            "first_session": min((s.started_at for s in summaries), default=None),
        },
    }
