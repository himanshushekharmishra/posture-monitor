"""WebSocket message formats between frontend/ and backend/.

Client -> server (JSON, one object per message):
  {"type": "frame", "landmarks": [[x, y, visibility], ... 33] | null, "pose_ms": 11.8}
  {"type": "calibrate"}            start calibration (countdown, then recording)
  {"type": "cancel_calibration"}
  {"type": "label", "kind": "correct" | "false_alarm" | "missed"}

Server -> client:
  {"type": "hello", "config": {...}, "calibrated": bool, "alerts_today": int}
  {"type": "frame", "state", "score", "slouch_seconds", "features", "note", "event",
   "alert": {"title", "message"} | null, "calibration": {...} | null,
   "calibrated": bool, "alerts_today": int}
  {"type": "calibration", "phase", "seconds_left", "samples", "message"}
  {"type": "labelled", "kind", "counts": {"correct", "false_alarm", "missed"}}
  {"type": "error", "message"}

Landmarks are normalised image coordinates from MediaPipe (0..1). The video itself
never leaves the browser.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from backend.session import CalibrationStatus, FrameResult


class FrameMessage(BaseModel):
    type: Literal["frame"]
    landmarks: list[Annotated[list[float], Field(min_length=2, max_length=4)]] | None = Field(
        default=None, max_length=33
    )
    pose_ms: float | None = Field(default=None, ge=0, le=10_000)


class CalibrateMessage(BaseModel):
    type: Literal["calibrate"]


class CancelCalibrationMessage(BaseModel):
    type: Literal["cancel_calibration"]


class LabelMessage(BaseModel):
    type: Literal["label"]
    kind: Literal["correct", "false_alarm", "missed"]


ClientMessage = Annotated[
    Union[FrameMessage, CalibrateMessage, CancelCalibrationMessage, LabelMessage],
    Field(discriminator="type"),
]
client_message = TypeAdapter(ClientMessage)


def calibration_payload(c: CalibrationStatus) -> dict:
    return {
        "phase": c.phase.value,
        "seconds_left": round(c.seconds_left, 1),
        "samples": c.samples,
        "message": c.message,
    }


def frame_payload(
    r: FrameResult, alert: dict | None, calibrated: bool, alerts_today: int
) -> dict:
    return {
        "type": "frame",
        "state": r.state.value,
        "score": None if r.score is None else round(r.score, 4),
        "slouch_seconds": round(r.slouch_seconds, 1),
        "features": None if r.features is None
        else {k: round(v, 4) for k, v in r.features.items()},
        "note": r.note,
        "event": r.event,
        "alert": alert,
        "calibration": None if r.calibration is None else calibration_payload(r.calibration),
        "calibrated": calibrated,
        "alerts_today": alerts_today,
    }
