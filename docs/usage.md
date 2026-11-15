# Usage

1. `scripts\setup.ps1`
2. `python -m src.main --calibrate` (sit upright; 3 s countdown, then 5 s recording)
3. `scripts\run.ps1` to run in the background (tray icon, no console window)

## Tray icon
The icon colour shows the current state: grey = away, green = good,
orange = slouching, red = alerted. Grey with two bars = paused.

- **Pause / Resume**: releases the camera (its light turns off) until resumed.
- **Recalibrate**: opens the calibration window, then continues monitoring.
- **Quit**: stops monitoring and closes the session in the log.

## Data
Everything stays in `data/output/` (gitignored). No camera frames are saved.
- `baseline.json`: your calibrated upright posture
- `posture.db`: SQLite `sessions` (start/end, avg CPU %, avg latency ms) and
  `events` (`slouch_start`, `alert`, `recovered`, `away` with the score)
- `app.log`: log file for the headless run

`python -m src.main --debug` runs in the console with the live skeleton window instead.
