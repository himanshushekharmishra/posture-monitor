# Posture Monitor

Privacy-first, real-time posture monitor. It uses your webcam and on-device pose
estimation (MediaPipe) to spot slouching and notifies you if it lasts. Use it as a
Windows background app with a tray icon, or in the browser. No frames are saved or
uploaded; only posture numbers and events are kept, on your machine.

## Web app
```powershell
python -m backend        # then open http://127.0.0.1:8000
```
The browser runs the pose model itself and sends only 33 body points per frame to
the local server (`backend/`), which scores your posture with the same engine as
the desktop app. The page (`frontend/`) shows your state, a score meter, alerts and
today's numbers. Calibrate, alerts and labelling all work from the page.

## Quick start (Windows)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\venv\Scripts\Activate.ps1
python -m src.main --calibrate   # sit upright: 3 s countdown, 5 s recording
python -m src.main --debug       # live skeleton, score and state
scripts\run.ps1                  # run in the background with a tray icon
```

## How it works
webcam (~5 FPS) -> MediaPipe PoseLandmarker -> neck/lean/tilt features compared
with your baseline -> smoothed score -> state machine (alert only after 30 s of
slouching, at most once per 7 min) -> notification + SQLite log + tray icon.
See [docs/architecture.md](docs/architecture.md).

## Commands
| Command | What it does |
|---|---|
| `python -m backend` | web app at http://127.0.0.1:8000 (`--port` to change) |
| `python -m src.main` | background mode with a tray icon (Pause, Recalibrate, Quit) |
| `python -m src.main --debug` | console + live window; press `s` to save landmarks as an example |
| `python -m src.main --calibrate` | record a new upright baseline |
| `python -m src.main --video data\input\clip.mp4` | run on a recorded video instead of the webcam |
| `python -m src.main --label` | labelled session: `y`/`n` after each alert, `m` for a missed slouch |
| `python scripts\benchmark.py` | measure CPU, latency and FPS into docs/benchmarks.md |
| `pytest -q` | run the tests |

Settings are in `config/settings.json`; override any of them per machine in
`.env` (see `config/env.example`). More in [docs/usage.md](docs/usage.md).

## Results
About 0.5% CPU and 12 ms per frame at 5 FPS on a Ryzen 7 5800H, measured so far
with nobody in frame, so expect somewhat more while it tracks you. Full numbers and
method: [docs/benchmarks.md](docs/benchmarks.md).
