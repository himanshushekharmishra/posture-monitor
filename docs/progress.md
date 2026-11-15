# Progress

Where the project stands, what has been checked, and what is left. Update this file
with every change (see the rule in `CLAUDE.md`).

Last updated: 2026-11-15, on `main` after merging `phase-1-capture-pose`.

## Status at a glance

| Area | State |
|---|---|
| Desktop app (5 build phases) | done |
| Web app (`backend/` + `frontend/`) | done; live webcam in the page not yet tried by a person |
| Tests | 71 passing (`pytest -q`) |
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
| Any website you visit could open a WebSocket to the local server (WebSockets ignore CORS) and, for example, overwrite your calibration | `/ws` only accepts browser connections whose Origin is the server itself | see git log |
| DNS rebinding: a site resolving its own name to 127.0.0.1 could read `/api/*` | requests must be addressed to an allowed host (`web_allowed_hosts`) | see git log |

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
