# Benchmarks

Measured 2026-11-15 08:44 with `python scripts\benchmark.py`.

## Summary (default `process_fps` = 5)

| Metric | Value |
|---|---|
| Avg CPU % (whole machine) | 0.5% (meets the <10% target) |
| Avg latency per frame (ms) | 12.1 (p95 12.3) |
| Processed FPS | 5.03 |
| Alert precision (30-min labelled session) | not measured yet |

## By frame rate

| Target FPS | Actual FPS | CPU % machine | CPU % one core | Frame ms mean / p95 / max | Pose ms mean / p95 | Camera read ms mean | Person in frame | Memory |
|---|---|---|---|---|---|---|---|---|
| 5 | 5.03 | 0.5% | 7% | 12.1 / 12.3 / 96.0 | 11.4 / 12.0 | 0.7 | 0% | 155 MB |
| 10 | 10.00 | 0.9% | 14% | 65.1 / 89.3 / 102.4 | 11.6 / 12.3 | 53.6 | 1% | 181 MB |
| 15 | 9.98 | 0.9% | 14% | 100.2 / 112.4 / 120.7 | 11.4 / 12.0 | 88.7 | 0% | 184 MB |

Model load time: 106 ms. Each pass ran for 30 s after a warm-up.

## How it was measured

- The full per-frame pipeline runs: camera read, PoseLandmarker (VIDEO mode), feature extraction, EMA and the state machine. Notifications and the SQLite log are off.
- **CPU % machine** is the process's CPU time over the pass divided by all logical cores (what Task Manager's Processes tab shows). **CPU % one core** is the same before dividing.
- **Frame ms** is the time from asking the camera for a frame to the state machine update. **Pose ms** is the model alone.
- **Person in frame** is the share of frames where a pose was found. The model does more work while tracking a person, so numbers with nobody in frame are optimistic.
- Baseline missing: features ran but no score was computed.
- **Alert precision** needs a 30-minute session where each alert is marked right or wrong by the user; it isn't measured yet.

## Findings

- Nobody was in frame for most of the run, so these numbers are a lower bound. Re-run while sitting at the desk for realistic figures.
- At 15 FPS the camera only delivered 10.0 FPS: each read waited 89 ms for a new frame, while the model took 11 ms. The camera, not the model, is the limit here (often auto-exposure in dim light).
- At the default 5 FPS one frame takes 12 ms of the 200 ms budget, so the pipeline could keep up with about 83 FPS if the camera allowed it.

## Machine

| | |
|---|---|
| CPU | AMD Ryzen 7 5800H with Radeon Graphics (8 cores / 16 threads) |
| RAM | 13.9 GB |
| OS | Windows 11 (10.0.26200) |
| Python | 3.12.13 |
| MediaPipe | 1.2.3 |
| Model | pose_landmarker_lite.task |
| Camera resolution | 640x480 |
