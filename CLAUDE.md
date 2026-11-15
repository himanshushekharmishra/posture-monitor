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
- src/tools/      capture (webcam + video file), pose, notifier, logger, tray,
                  examples  (all I/O lives here)
- src/utils/      geometry.py, timing.py, env.py (.env overrides)
- src/schemas/    dataclasses + enums (NOT named `types/`, which shadows the stdlib)
- config/settings.json  every threshold and tunable (overridable via .env / env vars)
- messages/alerts.json  notification text variants
- data/examples/  labelled landmark JSON used by tests (coordinates only)
- data/input/     recorded test videos (gitignored)
- data/output/    runtime files (gitignored)
- scripts/        PowerShell setup/run, benchmark.py, make_examples.py,
                  make_demo_data.py (fake sessions for README screenshots)
- docs/           architecture.md, usage.md, progress.md (status log), benchmarks.md (generated)
                  images/ (README diagrams + screenshots; how to retake: usage.md)
- backend/        FastAPI web server: protocol.py (WS messages), session.py (pure,
                  reuses src/engine), app.py (routes, request guard + I/O),
                  security.py. No OpenCV/MediaPipe.
- backend/auth/   accounts: passwords (scrypt), store (SQLite), ratelimit, sms,
                  oauth (Google/GitHub, state+PKCE), routes. Every account has a
                  username + password; secrets only in .env, never settings.json
- frontend/       plain HTML/CSS/JS, no build step; MediaPipe runs in the browser
                  and only landmarks are sent to the backend. login.html = auth,
                  index.html = dashboard (needs login): js/dashboard.js menu +
                  tabs, js/views/* pages, js/charts.js SVG charts. No inline scripts (CSP).
- tests/          pytest

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
- Never write camera frames to disk or send them anywhere.
- No magic numbers: read thresholds from config/settings.json.
- engine/ and utils/ are pure functions/classes with no camera, file or OS calls,
  so they can be unit-tested with fake landmarks.
- Python 3.11/3.12, type hints everywhere, dataclasses in src/schemas/.
- Target OS is Windows; scripts are PowerShell.
- Run `pytest -q` and keep it green before every commit.
- Work one build phase at a time; don't implement later phases early.
- Keep the .md files current: with every change, update docs/progress.md (status,
  commit table, what's checked, what's left) and any README/usage/architecture
  text the change makes out of date, in the same commit.
- One commit per phase or feature, so the history shows how the work progressed.

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

## Build phases (all done; details and what's left in docs/progress.md)
1. capture + pose + debug overlay (skeleton drawn at ~5 FPS)   done
2. features + calibration                                      done
3. state machine + notifier                                    done
4. logger + tray + headless run                                done
5. tests + benchmark numbers in docs/benchmarks.md             done
Since then: .env overrides, landmark examples, --video, --label, web app
(backend/ + frontend/). Next steps are user checks listed in docs/progress.md.
