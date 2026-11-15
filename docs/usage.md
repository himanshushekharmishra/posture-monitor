# Usage

1. `scripts\setup.ps1`
2. `python -m src.main --calibrate` (sit upright; 3 s countdown, then 5 s recording)
3. `scripts\run.ps1` to run in the background (tray icon, no console window)

## Web app
1. `python -m backend` and open http://127.0.0.1:8000 (Chrome, Edge or Firefox).
2. **Sign up** or **Log in**. Every account has a username and password:
   - **Sign up** by verifying with Google, GitHub or a phone code, then choosing a
     username and password. Next time you can log in with any of them.
   - Or **try it as a guest**: just a username and password, free for
     `guest_trial_days` (14). Connect Google, GitHub or a phone before it ends to
     keep the account; after that you'll be asked to.
3. **Start camera** and allow camera access. The pose model runs in the page; only
   33 body points per frame are sent to the server, never the video.
4. Sit upright and press **Calibrate** (3 s countdown, 5 s recording). Each account
   has its own calibration and history. The desktop app keeps its own.
5. **Turn on notifications** to get alerts while the tab is in the background.
   Monitoring keeps running in a background tab; closing the tab stops it.
6. After an alert, answer **Yes, I was** or **No, false alarm**; use
   **I slouched and got no alert** for misses. These feed the precision number.

### Setting up Google, GitHub and SMS
They're off until you add their keys to `.env` (see `config/env.example`):
- Google: create an OAuth client ID (Web application) in Google Cloud Console with
  redirect URI `http://127.0.0.1:8000/auth/google/callback`, then set
  `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
- GitHub: create an OAuth App at github.com/settings/developers with callback URL
  `http://127.0.0.1:8000/auth/github/callback`, then set `GITHUB_CLIENT_ID` and
  `GITHUB_CLIENT_SECRET`.
- Phone: with no SMS service, codes are printed in the server window and only work
  from the same computer. For real texts set `SMS_PROVIDER=twilio` and the
  `TWILIO_*` values.
If people reach the app at another address, set `WEB_PUBLIC_URL` to it (use https)
and register that address's callback URLs instead.

### Security
Passwords are hashed with scrypt; sessions are HttpOnly cookies (Secure on https)
stored only as hashes; wrong passwords lock an account for 15 minutes after 8 tries;
codes are single-use, expire in 5 minutes and allow 5 guesses; Google/GitHub sign-in
uses state and PKCE. Other websites can't use the server: changes must come from
its own pages as JSON, the socket only accepts the page's own origin, and requests
must be addressed to a host in `web_allowed_hosts` (`python -m backend --host <ip>`
adds that address). The page loads the MediaPipe runtime from cdn.jsdelivr.net and
its font from Google Fonts; the model comes from your server.

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
