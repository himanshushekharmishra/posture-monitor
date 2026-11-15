# Posture Monitor

Privacy-first, real-time posture and ergonomics monitor. It uses your webcam and
on-device pose estimation (MediaPipe) to detect slouching and send a desktop
notification. No frames are saved or uploaded.

## Quick start (Windows)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\venv\Scripts\Activate.ps1
python -m src.main --calibrate   # sit upright for 5 seconds
python -m src.main --debug       # live skeleton window
```

## Results
See [docs/benchmarks.md](docs/benchmarks.md).
