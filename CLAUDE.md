# Posture Monitor — CLAUDE.md

## Goal
A privacy-first background app for Windows. It uses the webcam and on-device pose
estimation (MediaPipe) to detect slouching in real time, then shows a desktop
notification. It must stay light enough to run all day (target: <10% CPU).

Architecture, folder roles, features and state machine: docs/architecture.md.
Status, phase history and what's left: docs/progress.md.

## Commands
- Setup:      powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
- Run:        python -m src.main          (debug window: python -m src.main --debug)
- Calibrate:  python -m src.main --calibrate
- Video:      python -m src.main --video data\input\clip.mp4 [--debug]
- Label:      python -m src.main --label  (y/n per alert, m = missed; for precision)
- Web app:    python -m backend           (http://127.0.0.1:8000)
- Tests:      pytest -q
- Benchmark:  python scripts\benchmark.py

## Rules
- Use the MediaPipe Tasks API only (mediapipe.tasks.python.vision.PoseLandmarker,
  running_mode=VIDEO, pass a monotonically increasing timestamp in ms).
  Never use `mp.solutions`.
- Never write camera frames to disk or send them anywhere. In the web app,
  MediaPipe runs in the browser and only landmarks reach the backend;
  backend/ never imports OpenCV or MediaPipe.
- Secrets live only in .env, never in config/settings.json.
- No magic numbers: read thresholds from config/settings.json.
- engine/ and utils/ are pure functions/classes with no camera, file or OS calls,
  so they can be unit-tested with fake landmarks. All I/O lives in src/tools/.
- Dataclasses go in src/schemas/; never rename it to `types/` (shadows the stdlib).
- frontend/ is plain HTML/CSS/JS with no build step and no inline scripts (CSP).
- Python 3.11/3.12, type hints everywhere.
- Target OS is Windows; scripts are PowerShell.
- Run `pytest -q` and keep it green before every commit.
- Work one build phase at a time; don't implement later phases early.
- Keep the .md files current: with every change, update docs/progress.md (status,
  commit table, what's checked, what's left) and any README/usage/architecture
  text the change makes out of date, in the same commit.
- One commit per phase or feature, so the history shows how the work progressed.
