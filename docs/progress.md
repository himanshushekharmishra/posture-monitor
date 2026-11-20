# Progress

Where the project stands, what has been checked, and what is left. Update this file
with every change (see the rule in `CLAUDE.md`).

Last updated: 2026-11-20, on `main`, after adding the 3D voxel body to the web page.

## Status at a glance

| Area | State |
|---|---|
| Desktop app (5 build phases) | done |
| Web app (`backend/` + `frontend/`) | done, with accounts; live webcam in the page not yet tried by a person |
| Code review | done: 16 problems found and fixed (table below) |
| Tests | 124 passing (`pytest -q`) |
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
| This progress log; docs-update rule in `CLAUDE.md` | `8ec1746` |
| README pictures: pipeline and posture diagrams, web app screenshots (light and dark), state machine | `26da4d5`, `27bfa01` |
| `scripts/make_demo_data.py` and steps for retaking the README screenshots | `04ef5e9` |
| `setup.ps1` really uses `py -3.12`/`-3.11`: on Windows PowerShell 5.1 the version flag was dropped, so it checked the default Python and fell back to uv; `.claude/launch.json` to start the web app from Claude Code | `6f29b08` |
| `CLAUDE.md` trimmed to goal, commands and rules; folder map, pipeline, features, state machine and phase list now live only in `docs/architecture.md` and this file | `e2d6a57` |
| Warning when a calibration comes out tilted (over `calibration_max_tilt_degrees`, 8): tilt is scored against the baseline, so a crooked one pushes level sitting toward an alert. Shown in the console, as a tray notification and in the web page's banner | `d39dcd4` |
| `requirements.txt` pins the exact versions the tests pass with (MediaPipe 1.2.3, NumPy 2.5.5, FastAPI 0.165.0, ...), so every laptop installs the same set | `7c2996a` |
| Known limits and `backend/__main__.py` no longer say the web server has no login (accounts were added); the reason to stay on `127.0.0.1` is plain HTTP | `ec2cb9f` |
| GitHub Actions runs `pytest -q` on Windows with Python 3.12 on every push and pull request (`.github/workflows/tests.yml`); no camera or model needed | `f4aa14d` |
| MIT `LICENSE` and a License section in the README, now that a copy of the repo is public | `f68ae56` |
| Web page: 3D voxel body (`frontend/js/voxelbody.js`, WebGL2 with custom vertex/fragment shaders) instead of the flat skeleton; cracks while slouching, shatters on an alert, reassembles on recovery; **Show lines** toggle. Rendered in headless Chrome with the example poses (good, slouching, alerted) and checked that voxels line up with the landmarks; not yet tried with a live webcam | this commit |

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
| Pressing `s` twice within a second overwrote the first saved example | names get a `_2`, `_3`… suffix instead | `f0f5b65` |
| The settings-key test didn't scan `backend/` or every script | it scans `src/`, `backend/` and `scripts/` | `f0f5b65` |

Also re-checked after these fixes: the real web page still connects (its own
origin is accepted), a request with a foreign Host header gets 400, and a running
desktop monitor reloaded a baseline written by another process mid-run.

## Web accounts and dashboard

Goal: a secure login page (log in / sign up with Google, GitHub or phone, or a guest
trial; every account has a username and password), then a dashboard with profile,
previous sessions, a slouch meter and settings.

| Step | State | Commit |
|---|---|---|
| Backend: accounts, sessions, phone codes, Google/GitHub OAuth, per-account data | done | `5648b07` |
| Login and sign-up page; app page shows the account, log out, guest trial days | done | `8dd324d` |
| Dashboard backend: session history, slouch insights, profile edit, password change, delete account | done | `c24d042` |
| Dashboard pages: side menu, profile, previous sessions, slouch meter, settings | done | `b2bf86f` |
| New look: sky blue and white colours, floating buttons, a real dropdown menu, login errors under the field | done | `2652edb` |

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

Dashboard checked in a browser with a seeded test account (10 days of sessions):
the slouch meter (hero number, 14-day chart, hour-of-day chart, range buttons),
previous sessions with a timeline, profile, settings (bad email caught, name saved
and shown in the header, phone connected which ended the guest trial), the menu
collapsing on desktop and dropping down at phone width, no sideways scrolling.
Fixed on the way: an open tab with the camera off counted as monitoring time (web
sessions now cover only time with frames; test added); opening `#meter` jumped down
the page because the score meter had the id `meter`; overlapping last labels on the
hour chart; wrapping times in the session timeline; profile spacing and link colour.
The login page's privacy line was removed on request (`a76c67d`).

New look (2026-11-15): pale sky blue and white with a deep navy for text and a clear
blue for controls (calm and focused), plus a warm amber ring for keyboard focus.
Buttons float on a soft blue shadow, lift when you point at them and press down when
clicked (no movement if the system asks for reduced motion). The **Menu** button
now drops a list down under itself on every screen size, shows the page you're on,
and closes when you pick a page, click outside, press Escape or tab away; arrow keys
move through it. On the login page, mistakes show in small red text right under the
field they're about (a wrong username or password under the password box, with both
boxes outlined), and clear as you type. Checked in a browser: empty and wrong login,
mismatched guest passwords, guest sign-up into the dashboard, the dropdown on desktop
and at phone width in dark mode, no sideways scrolling. The throwaway test account
was deleted afterwards.

Needs you: Google and GitHub sign-in work once you register the app and put the
IDs in `.env` (steps in `config/env.example`); real SMS needs a Twilio account.
Until then phone codes are printed in the server window, and only for people on
the same computer.

## Found while testing on your laptop (2026-11-15)

| Problem | Fix | Commit |
|---|---|---|
| "Start camera" said "Close other apps using it" for every failure, including when no camera exists | separate messages for blocked permission, no camera found (check the laptop's camera key or privacy switch) and camera in use | `01058f6` |
| Browsers could keep running old scripts from their cache after an update | `.js`, `.css` and `.html` are revalidated on every load (unchanged files return a cheap 304) | `01058f6` |

Camera status on this laptop: Windows lists the "Integrated Camera" with status
Unknown (not connected) and neither Chrome nor Python can open it, although it
worked earlier the same day and every camera privacy setting is on (Allow). Most
likely the camera privacy key or switch is on. Not something the app can fix.

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
  - `setup.ps1` on a second laptop (2026-11-20) with Python 3.12 from the py launcher
    and no uv: found 3.12 after the fix, installed MediaPipe 1.2.3, 122 tests pass, and
    the web login page loads with no console errors
  - `--video` and `--label` on a generated test clip
  - the web page in a browser: light and dark themes, phone width, pose model
    loading on the GPU, and a full calibrate, slouch, alert and label run over
    the page's WebSocket using the example poses

## Left to do

Needs you:
1. Calibrate: `python -m src.main --calibrate` (or **Calibrate** in the web page).
   The baseline saved on 2026-11-20 has the shoulders tilted 13 degrees, so redo it
   sitting level.
2. Try the web page with your webcam in Chrome or Edge (`python -m backend`).
   The built-in test browser blocks cameras, so this hasn't been tried yet. Check
   that the 3D voxel body follows you smoothly and stays aligned with the video.
3. Let a real slouch alert fire, and try `scripts\run.ps1` with Recalibrate from the tray.
4. Do a 30-minute labelled session (`python -m src.main --label` or the web page's
   yes/no buttons) to get the alert precision number.
5. Rerun `python scripts\benchmark.py` while sitting at the desk and commit
   `docs/benchmarks.md`.
6. Save a few real poses with `s` in `--debug` and label them in `data/examples/`.

Optional:
- Invite friends as collaborators on the private GitHub repo
  (github.com/Ayushman2804/posture-monitor, pushed 2026-11-15).
- A public copy lives at github.com/himanshushekharmishra/posture-monitor
  (git remote `himanshu`, created 2026-11-20); push to both remotes to keep it current.
- FastAPI's test client prints a deprecation warning about `httpx`; harmless.

## Known limits

- The web server has accounts but speaks plain HTTP; keep it on `127.0.0.1`. Browsers
  only allow the camera there or on HTTPS, and on a network passwords and session
  cookies would travel unencrypted.
- The web page loads the MediaPipe runtime from cdn.jsdelivr.net and its font from
  Google Fonts. The model comes from the local server, and video never leaves the page.
- Closing the browser tab stops web monitoring; the desktop app is for all-day use.
