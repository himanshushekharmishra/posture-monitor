# Posture Monitor — CLAUDE.md

## Goal
A privacy-first background app for Windows. It uses the webcam and on-device pose
estimation (MediaPipe) to detect slouching in real time, then shows a desktop
notification. It must stay light enough to run all day (target: <10% CPU).

## Pipeline
webcam (OpenCV, ~5 FPS) -> PoseLandmarker (lite .task) -> feature extraction
-> EMA smoothing -> state machine -> notifier (plyer) + SQLite logger
Side inputs: calibration baseline (data/output/baseline.json), tray icon (pystray).

## Folder map
- src/engine/     features.py, calibration.py, state.py  (pure logic, NO I/O)
- src/workflows/  monitor_loop.py, calibrate_flow.py     (orchestration)
- src/tools/      capture, pose, notifier, logger, tray  (all I/O lives here)
- src/utils/      geometry.py, timing.py
- src/schemas/    dataclasses + enums (NOT named `types/`, which shadows the stdlib)
- config/settings.json  every threshold and tunable
- messages/alerts.json  notification text variants
- data/output/    runtime files (gitignored)
- scripts/        PowerShell setup/run + benchmark.py
- tests/          pytest

## Commands
- Setup:      powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
- Run:        python -m src.main          (debug window: python -m src.main --debug)
- Calibrate:  python -m src.main --calibrate
- Tests:      pytest -q
- Benchmark:  python scripts\benchmark.py

## Rules
- Use the MediaPipe Tasks API only (mediapipe.tasks.python.vision.PoseLandmarker,
  running_mode=VIDEO, pass a monotonically increasing timestamp in ms).
  Never use `mp.solutions`.
- Never write camera frames to disk or send them anywhere.
- No magic numbers: read thresholds from config/settings.json.
- engine/ and utils/ are pure functions/classes with no camera, file or OS calls,
  so they can be unit-tested with fake landmarks.
- Python 3.11/3.12, type hints everywhere, dataclasses in src/schemas/.
- Target OS is Windows; scripts are PowerShell.
- Run `pytest -q` and keep it green before every commit.
- Work one build phase at a time; don't implement later phases early.

## Landmarks used (MediaPipe Pose, 33 points, normalized 0-1)
0 nose, 7 left ear, 8 right ear, 11 left shoulder, 12 right shoulder.

## Features (normalized by shoulder width)
- neck_ratio    = (shoulder_mid.y - ear_mid.y) / shoulder_width   (drops when head goes forward/down)
- lean_ratio    = shoulder_width / baseline_shoulder_width         (>1 when leaning toward screen)
- shoulder_tilt = angle of shoulder line in degrees
- head_tilt     = angle of ear line in degrees
- score = weighted deviation from baseline (weights in settings.json)

## State machine
AWAY (no person for away_timeout) | GOOD | SLOUCHING (< persist_seconds) |
ALERTED (notify, then cooldown). Recovery -> GOOD, logged as `recovered`.

## Build phases
1. capture + pose + debug overlay (skeleton drawn at ~5 FPS)   <- CURRENT
2. features + calibration
3. state machine + notifier
4. logger + tray + headless run
5. tests + benchmark numbers in docs/benchmarks.md
