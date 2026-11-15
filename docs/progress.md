# Progress

Where the project stands, what has been checked, and what is left. Update this file
with every change (see the rule in `CLAUDE.md`).

Last updated: 2026-11-15, on `main`, after the code review fixes.

## Status at a glance

| Area | State |
|---|---|
| Desktop app (5 build phases) | done |
| Web app (`backend/` + `frontend/`) | done, with accounts; live webcam in the page not yet tried by a person |
| Code review | done: 16 problems found and fixed (table below) |
| Tests | 120 passing (`pytest -q`) |
| Benchmarks | measured, but only with nobody in frame |
| Alert precision | not measured yet (needs a 30-minute labelled session) |

## Build phases

Each phase is one commit, so the history shows how the app was built up.

| Phase | What it added | Commit |
|---|---|---|
| Scaffold | folder layout, `CLAUDE.md`, geometry helpers and tests | `da509b3` |
| 1 | webcam capture, MediaPipe pose (VIDEO mode), frame throttle, debug skeleton window | `d7af71a` |
| 2 | posture features, weighted score, median-based calibration (`--calibrate`) | `33911ef` |
| 3 | EMA smoothing, AWAY/GOOD/SLOUCHING/ALERTED state machine, desktop notifications | `b9fc100` |
| 4 | SQLite session/event log, tray icon (Pause, Recalibrate, Quit), background run | `ef829f3` |
| 5 | benchmark script and numbers, end-to-end pipeline tests, settings-key test | `86662a9` |

## After the phases

| Change | Commit |
|---|---|
| `.env` and environment-variable overrides for any setting | `bd39cc4` |
| Labelled landmark examples in `data/examples/`, `s` key to record real ones | `546dc87` |
| `--video` input for recorded test videos (app and benchmark) | `6865ad9` |
| `--label` mode and `labels` table for measuring alert precision | `8bacddc` |
| Real `architecture.md`, README and usage docs | `8647725` |
| `setup.ps1` finds Python 3.11/3.12 via py, uv or PATH | `314d7c8` |
| Settings-override log line actually shown | `050d3e8` |
| `.gitattributes`: LF line endings, binary files marked | `285c139` |
| MediaPipe/LiteRT startup log spam hidden (`quiet_native_logs`) | `d6e6b59` |
| Web backend: FastAPI + WebSocket, reuses `src/engine` | `f41868a` |
| Web frontend: in-browser pose estimation, live posture view | `7ca0508` |
| Web app docs | `2a84522` |
| Benchmark rerun at 5/10/15 FPS (nobody in frame) | `a3d867c` |
| This progress log; docs-update rule in `CLAUDE.md` | this commit |

## Fixes from the code review (2026-11-15)

Each problem below was reproduced first, then fixed with a test that covers it.

| Problem | Fix | Commit |
|---|---|---|
| Any website you visit could open a WebSocket to the local server (WebSockets ignore CORS) and, for example, overwrite your calibration | `/ws` only accepts browser connections whose Origin is the server itself | `3d0aa00` |
| DNS rebinding: a site resolving its own name to 127.0.0.1 could read `/api/*` | requests must be addressed to an allowed host (`web_allowed_hosts`) | `3d0aa00` |
| One malformed or binary WebSocket message crashed the connection handler | it gets an error reply and the socket stays open | `476e4a0` |
| Web page: after a reconnect it could stay on "Cancel calibration" or show an alert the server no longer knows | a new connection resets calibration and alert state | `476e4a0` |
| Web page: stopping the camera left the last state (e.g. "Slouching") on screen and an unfinished calibration running | the readout resets to "Camera is off" and calibration is cancelled | `476e4a0` |
| Web page: browser notifications throw on Android Chrome | caught; the in-page alert still shows | `476e4a0` |
| Web page: an old auto-hide timer could hide a newly started calibration's banner | the timer is cleared on each update | `476e4a0` |
| Tray **Recalibrate** while another app had the camera stopped the whole background app | the error is caught, you get a notification, monitoring continues | `37c19d4` |
| An error while updating the tray icon would stop the monitoring thread | status-listener errors are logged and ignored | `37c19d4` |
| Starting `run.ps1` twice ran two monitors fighting over the camera, with two tray icons | a Windows named mutex allows one instance; the second says "Already running" and exits | `37c19d4` |
| A baseline file with shoulder width 0 crashed scoring (division by zero); odd calibrations (ears below shoulders) were accepted | baselines are checked on load and when built; a bad file is ignored, a bad calibration fails with a reason | `c3d150a` |
| Nonsense settings (e.g. `PROCESS_FPS=0`, `EMA_ALPHA=5`) failed later, far from the cause | all settings are checked at start-up and every problem is listed; in background mode it's shown as a notification | `c3d150a` |
| The docs said desktop and web share one calibration, but each process read `baseline.json` only at start, so calibrating in one didn't reach the other while running | both watch the file (one check every 2 s) and reload it when it changes | `be3ed91` |
| The tray's "alerts today" count kept yesterday's number after midnight until the next alert | it's recounted when the date changes | `be3ed91` |
| Pressing `s` twice within a second overwrote the first saved example | names get a `_2`, `_3`… suffix instead | this commit |
| The settings-key test didn't scan `backend/` or every script | it scans `src/`, `backend/` and `scripts/` | this commit |

Also re-checked after these fixes: the real web page still connects (its own
origin is accepted), a request with a foreign Host header gets 400, and a running
desktop monitor reloaded a baseline written by another process mid-run.

## Web accounts (in progress)

Goal: a secure login page (log in / sign up with Google, GitHub or phone, or a guest
trial; every account has a username and password), then a dashboard with profile,
previous sessions, a slouch meter and settings.

| Step | State | Commit |
|---|---|---|
| Backend: accounts, sessions, phone codes, Google/GitHub OAuth, per-account data | done | `5648b07` |
| Login and sign-up page; app page shows the account, log out, guest trial days | done | this commit |
| Dashboard backend: session history, slouch insights, profile edit, password change, delete account | done | this commit |
| Dashboard pages: side menu, profile, previous sessions, slouch meter, settings | next | |

Security built in: scrypt password hashes; session cookies that are HttpOnly,
SameSite=Lax and Secure on https, stored only as hashes; lockout after 8 wrong
passwords and per-network rate limits; single-use 6-digit phone codes that expire
in 5 minutes, stored as HMACs, with limited guesses; OAuth with `state`, PKCE and
a browser-bound cookie; cross-site and non-JSON writes refused; strict security
headers (CSP, no framing); the same error for unknown users and wrong passwords.

Checked in a browser: guest sign-up (a mismatched password was caught first), phone
sign-up with a console code then choosing a username and password, log out, a wrong
password ("Wrong username or password."), log in, the app page showing the account
and connecting, the pose model loading under the new security headers, and the
login page at phone width with an error message. Fixed on the way: a new 14-day
trial showed "13 days left" (rounding), and provider buttons lacked accessible names.

Needs you: Google and GitHub sign-in work once you register the app and put the
IDs in `.env` (steps in `config/env.example`); real SMS needs a Twilio account.
Until then phone codes are printed in the server window, and only for people on
the same computer.

## What has been checked

- **Automated**: every commit above passes `pytest -q` on its own. The suite covers
  geometry, features, calibration, the state machine with simulated time, the full
  pure pipeline, the landmark examples, video input, the logger and labels, tray
  status, `.env` overrides, the web session logic and the real FastAPI app over
  HTTP and WebSocket.
- **Run by hand**:
  - webcam capture and pose at 5 FPS (about 12 ms per frame)
  - a desktop notification appeared on screen
  - the tray run paused, resumed and quit cleanly (scripted)
  - `setup.ps1` on a fresh folder (fell back to uv) and on the project
  - `--video` and `--label` on a generated test clip
  - the web page in a browser: light and dark themes, phone width, pose model
    loading on the GPU, and a full calibrate, slouch, alert and label run over
    the page's WebSocket using the example poses

## Left to do

Needs you:
1. Calibrate: `python -m src.main --calibrate` (or **Calibrate** in the web page).
2. Try the web page with your webcam in Chrome or Edge (`python -m backend`).
   The built-in test browser blocks cameras, so this hasn't been tried yet.
3. Let a real slouch alert fire, and try `scripts\run.ps1` with Recalibrate from the tray.
4. Do a 30-minute labelled session (`python -m src.main --label` or the web page's
   yes/no buttons) to get the alert precision number.
5. Rerun `python scripts\benchmark.py` while sitting at the desk and commit
   `docs/benchmarks.md`.
6. Save a few real poses with `s` in `--debug` and label them in `data/examples/`.

Optional:
- Push to GitHub (there's no remote yet).
- FastAPI's test client prints a deprecation warning about `httpx`; harmless.

## Known limits

- The web server has no login; keep it on `127.0.0.1`.
- The web page loads the MediaPipe runtime from cdn.jsdelivr.net and its font from
  Google Fonts. The model comes from the local server, and video never leaves the page.
- Closing the browser tab stops web monitoring; the desktop app is for all-day use.
