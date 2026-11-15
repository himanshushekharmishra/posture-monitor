# Usage

1. `scripts\setup.ps1`
2. `python -m src.main --calibrate` (sit upright; 3 s countdown, then 5 s recording)
3. `scripts\run.ps1` to run in the background (tray icon, no console window)

## Web app
1. `python -m backend` and open http://127.0.0.1:8000 (Chrome, Edge or Firefox).
2. **Start camera** and allow camera access. The pose model runs in the page; only
   33 body points per frame are sent to the local server, never the video.
3. Sit upright and press **Calibrate** (3 s countdown, 5 s recording). The baseline
   is shared with the desktop app, so calibrating in either one is enough.
4. **Turn on notifications** to get alerts while the tab is in the background.
   Monitoring keeps running in a background tab; closing the tab stops it.
5. After an alert, answer **Yes, I was** or **No, false alarm**; use
   **I slouched and got no alert** for misses. These feed the precision number.

Keep the server on `127.0.0.1`: browsers only allow the camera on localhost or
HTTPS, and the server has no login. Other websites can't talk to it: the socket
only accepts the page's own origin, and requests must be addressed to a host in
`web_allowed_hosts` (`python -m backend --host <ip>` adds that address). The page loads the MediaPipe runtime from
cdn.jsdelivr.net and its font from Google Fonts; the model comes from your server.

## Tray icon
The icon colour shows the current state: grey = away, green = good,
orange = slouching, red = alerted. Grey with two bars = paused.

- **Pause / Resume**: releases the camera (its light turns off) until resumed.
- **Recalibrate**: opens the calibration window, then continues monitoring.
- **Quit**: stops monitoring and closes the session in the log.

## Debug window
`python -m src.main --debug` shows the skeleton, the features, the smoothed score
and the state, and prints per-frame latency in the console.

- `q` or `Esc`: quit
- `s`: save the current landmarks (coordinates only, no image) to
  `data/examples/recorded_<time>.json`. See `data/examples/README.md` to label them
  so the tests use them.

## Recorded videos
Put a recording of yourself at the desk in `data/input/` (gitignored), for example
one made with the Windows Camera app, then:

```powershell
python -m src.main --video data\input\desk.mp4 --debug   # watch it
python scripts\benchmark.py --video data\input\desk.mp4  # repeatable benchmark
```

The video plays in real time and the run stops at its end (the benchmark loops it).

## Measuring alert precision
1. Calibrate, then run `python -m src.main --label` for at least 30 minutes of
   normal work.
2. After each alert, press `y` in the window if you really were slouching or `n` if
   not. Press `m` whenever you notice you've been slouching and got no alert.
3. Quit with `q`. The console prints the session's precision, and the next
   `python scripts\benchmark.py` puts the total in docs/benchmarks.md.

## Settings
Every threshold is in `config/settings.json`. To change one on this machine only,
copy `config/env.example` to `.env` in the project root and set the key in upper
case (`PERSIST_SECONDS=45`). Environment variables win over `.env`:
`$env:CAMERA_INDEX = "1"; python -m src.main --debug`.

## Data
Everything stays in `data/output/` (gitignored). No camera frames are saved.
- `baseline.json`: your calibrated upright posture
- `posture.db`: SQLite `sessions` (start/end, avg CPU %, avg latency ms),
  `events` (`slouch_start`, `alert`, `recovered`, `away` with the score) and
  `labels` (from `--label` sessions)
- `app.log`: log file for the background run
