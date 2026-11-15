"""Measure CPU %, per-frame latency (ms) and processed FPS.  Phase 5.

Runs the real pipeline (camera -> pose -> features -> EMA -> state machine) at one
or more frame rates and writes the results to docs/benchmarks.md. No notifications
are sent, nothing is logged to the database, and no frames are saved.

Sit in front of the camera while it runs: the pose model costs more when it is
tracking a person than when the frame is empty.

    python scripts\\benchmark.py                   # process_fps, 10 and 15 FPS, 30 s each
    python scripts\\benchmark.py --fps 5 --seconds 60
    python scripts\\benchmark.py --no-write        # print only
    python scripts\\benchmark.py --video data\\input\\desk.mp4   # repeatable; loops the video
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mediapipe  # noqa: E402
import psutil  # noqa: E402

from src.engine.features import deviation_score, extract_features  # noqa: E402
from src.engine.state import Ema, PostureStateMachine  # noqa: E402
from src.main import read_settings  # noqa: E402
from src.schemas.models import Baseline  # noqa: E402
from src.tools.capture import open_source  # noqa: E402
from src.tools.pose import PoseEstimator  # noqa: E402
from src.utils.timing import FrameThrottle, LatencyStats, LatencyTimer  # noqa: E402
from src.tools.logger import LabelSummary, SessionLogger  # noqa: E402
from src.workflows.calibrate_flow import load_baseline  # noqa: E402

DOC_PATH = ROOT / "docs" / "benchmarks.md"


@dataclass(frozen=True)
class PassResult:
    target_fps: float
    seconds: float
    fps: float
    cpu_machine: float  # % of the whole machine (all logical cores)
    cpu_core: float  # % of one core, as Task Manager's per-process view can show it
    read: LatencyStats
    pose: LatencyStats
    frame: LatencyStats  # read + pose + features + state machine
    person_share: float
    rss_mb: float


class Pipeline:
    """Everything the monitor does per frame except notifying and logging."""

    def __init__(
        self, settings: dict, baseline: Baseline | None, model_path: str,
        video: Path | None = None,
    ) -> None:
        self.settings = settings
        self.baseline = baseline
        self.min_vis = float(settings["min_visibility"])
        self.cam = open_source(settings, video, loop=True)
        with LatencyTimer() as t:
            self.pose = PoseEstimator(model_path)
        self.model_load_ms = t.ms
        self.t0 = time.monotonic()

    def close(self) -> None:
        self.pose.close()
        self.cam.release()

    def run(self, fps: float, seconds: float, record: bool = True) -> PassResult | None:
        throttle = FrameThrottle(fps)
        ema = Ema(float(self.settings["ema_alpha"]))
        machine = PostureStateMachine.from_settings(self.settings)
        proc = psutil.Process()
        proc.cpu_percent(None)
        read_ms: list[float] = []
        pose_ms: list[float] = []
        frame_ms: list[float] = []
        person = 0
        start = time.monotonic()
        while time.monotonic() - start < seconds:
            throttle.wait()
            with LatencyTimer() as total:
                with LatencyTimer() as r:
                    frame = self.cam.read()
                if frame is None:
                    continue
                now = time.monotonic()
                with LatencyTimer() as p:
                    landmarks = self.pose.detect(frame, int((now - self.t0) * 1000))
                score = None
                if landmarks:
                    person += 1
                    f = extract_features(landmarks, self.baseline)
                    if self.baseline and f.visibility >= self.min_vis:
                        score = ema.update(deviation_score(f, self.baseline, self.settings))
                machine.update(score, now)
            read_ms.append(r.ms)
            pose_ms.append(p.ms)
            frame_ms.append(total.ms)
        elapsed = time.monotonic() - start
        cpu_core = proc.cpu_percent(None)
        if not record or not frame_ms:
            return None
        return PassResult(
            target_fps=fps,
            seconds=elapsed,
            fps=len(frame_ms) / elapsed,
            cpu_machine=cpu_core / (psutil.cpu_count() or 1),
            cpu_core=cpu_core,
            read=LatencyStats.from_values(read_ms),
            pose=LatencyStats.from_values(pose_ms),
            frame=LatencyStats.from_values(frame_ms),
            person_share=person / len(frame_ms),
            rss_mb=proc.memory_info().rss / 2**20,
        )


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or "unknown CPU"


def machine_info(settings: dict, video: Path | None = None) -> dict[str, str]:
    return {
        "Frame source": f"video {video.name} (looped)" if video else "webcam",
        "CPU": f"{cpu_name()} ({psutil.cpu_count(logical=False)} cores / "
               f"{psutil.cpu_count()} threads)",
        "RAM": f"{psutil.virtual_memory().total / 2**30:.1f} GB",
        "OS": f"{platform.system()} {platform.release()} ({platform.version()})",
        "Python": platform.python_version(),
        "MediaPipe": mediapipe.__version__,
        "Model": Path(settings["model_path"]).name,
        "Camera resolution": "from the video" if video
        else f"{settings['frame_width']}x{settings['frame_height']}",
    }


def precision_text(labels: LabelSummary | None) -> str:
    if labels is None or labels.labelled_alerts == 0:
        if labels and labels.missed:
            return f"no alerts labelled yet ({labels.missed} missed slouches reported)"
        return "not measured yet (run `python -m src.main --label` for 30 min)"
    text = (f"{labels.precision:.0%} ({labels.correct} of {labels.labelled_alerts} alerts right, "
            f"{labels.missed} missed slouches, {labels.minutes:.0f} min over "
            f"{labels.sessions} session{'s' if labels.sessions != 1 else ''})")
    if labels.minutes < 30:
        text += "; under 30 min, so treat as preliminary"
    return text


def load_labels(db_path: Path) -> LabelSummary | None:
    if not db_path.is_file():
        return None
    lg = SessionLogger(db_path)
    try:
        return lg.label_summary()
    finally:
        lg.close()


def render_markdown(
    results: list[PassResult], info: dict[str, str], model_load_ms: float,
    default_fps: float, calibrated: bool, labels: LabelSummary | None = None,
) -> str:
    main = next((r for r in results if r.target_fps == default_fps), results[0])
    target_ok = "meets" if main.cpu_machine < 10 else "misses"
    precision = precision_text(labels)
    lines = [
        "# Benchmarks",
        "",
        f"Measured {datetime.now().astimezone():%Y-%m-%d %H:%M} with `python scripts\\benchmark.py`.",
        "",
        f"## Summary (default `process_fps` = {default_fps:g})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Avg CPU % (whole machine) | {main.cpu_machine:.1f}% ({target_ok} the <10% target) |",
        f"| Avg latency per frame (ms) | {main.frame.mean:.1f} (p95 {main.frame.p95:.1f}) |",
        f"| Processed FPS | {main.fps:.2f} |",
        f"| Alert precision (30-min labelled session) | {precision} |",
        "",
        "## By frame rate",
        "",
        "| Target FPS | Actual FPS | CPU % machine | CPU % one core | Frame ms mean / p95 / max "
        "| Pose ms mean / p95 | Camera read ms mean | Person in frame | Memory |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.target_fps:g} | {r.fps:.2f} | {r.cpu_machine:.1f}% | {r.cpu_core:.0f}% "
            f"| {r.frame.mean:.1f} / {r.frame.p95:.1f} / {r.frame.max:.1f} "
            f"| {r.pose.mean:.1f} / {r.pose.p95:.1f} | {r.read.mean:.1f} "
            f"| {r.person_share:.0%} | {r.rss_mb:.0f} MB |"
        )
    lines += [
        "",
        f"Model load time: {model_load_ms:.0f} ms. Each pass ran for {results[0].seconds:.0f} s "
        "after a warm-up.",
        "",
        "## How it was measured",
        "",
        "- The full per-frame pipeline runs: camera read, PoseLandmarker (VIDEO mode), feature "
        "extraction, EMA and the state machine. Notifications and the SQLite log are off.",
        "- **CPU % machine** is the process's CPU time over the pass divided by all logical "
        "cores (what Task Manager's Processes tab shows). **CPU % one core** is the same before "
        "dividing.",
        "- **Frame ms** is the time from asking the camera for a frame to the state machine "
        "update. **Pose ms** is the model alone.",
        "- **Person in frame** is the share of frames where a pose was found. The model does "
        "more work while tracking a person, so numbers with nobody in frame are optimistic.",
        f"- Baseline {'loaded' if calibrated else 'missing'}: "
        + ("scores were computed." if calibrated else "features ran but no score was computed."),
        "- **Alert precision** = alerts marked right / all labelled alerts, from "
        "`python -m src.main --label` sessions (y/n after each alert, m for a slouch with no "
        "alert), read from the `labels` table in the SQLite log.",
        "",
    ]
    findings = []
    if all(r.person_share < 0.5 for r in results):
        findings.append(
            "Nobody was in frame for most of the run, so these numbers are a lower bound. "
            "Re-run while sitting at the desk for realistic figures."
        )
    for r in results:
        if r.fps < 0.9 * r.target_fps:
            findings.append(
                f"At {r.target_fps:g} FPS the camera only delivered {r.fps:.1f} FPS: each read "
                f"waited {r.read.mean:.0f} ms for a new frame, while the model took "
                f"{r.pose.mean:.0f} ms. The camera, not the model, is the limit here "
                "(often auto-exposure in dim light)."
            )
    headroom = 1000 / main.frame.mean if main.frame.mean else 0
    findings.append(
        f"At the default {default_fps:g} FPS one frame takes {main.frame.mean:.0f} ms of the "
        f"{1000 / default_fps:.0f} ms budget, so the pipeline could keep up with about "
        f"{headroom:.0f} FPS if the camera allowed it."
    )
    lines += ["## Findings", "", *[f"- {f}" for f in findings], ""]
    lines += [
        "## Machine",
        "",
        "| | |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in info.items()],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    settings, applied = read_settings()
    if applied:
        print(f"Settings overridden: {', '.join(applied)}")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=30, help="length of each pass")
    ap.add_argument("--warmup", type=float, default=2, help="unrecorded warm-up seconds")
    ap.add_argument("--fps", type=float, nargs="+",
                    default=sorted({float(settings["process_fps"]), 10.0, 15.0}))
    ap.add_argument("--no-write", action="store_true", help="don't update docs/benchmarks.md")
    ap.add_argument("--video", type=Path, help="use a recorded video (looped) instead of the webcam")
    args = ap.parse_args()

    baseline = load_baseline(ROOT / settings["baseline_path"])
    video = args.video.resolve() if args.video else None
    pipe = Pipeline(settings, baseline, str((ROOT / settings["model_path"]).resolve()), video)
    results: list[PassResult] = []
    try:
        pipe.run(max(args.fps), args.warmup, record=False)
        for fps in args.fps:
            print(f"Benchmarking {fps:g} FPS for {args.seconds:g} s...", flush=True)
            r = pipe.run(fps, args.seconds)
            if r is None:
                print("  no frames from the camera")
                continue
            results.append(r)
            print(
                f"  {r.fps:.2f} FPS, CPU {r.cpu_machine:.1f}% of machine "
                f"({r.cpu_core:.0f}% of one core), frame {r.frame.mean:.1f} ms "
                f"(p95 {r.frame.p95:.1f}), pose {r.pose.mean:.1f} ms, "
                f"person in {r.person_share:.0%} of frames",
                flush=True,
            )
    finally:
        pipe.close()

    if not results:
        raise SystemExit("No results; is the camera available?")
    if all(r.person_share < 0.5 for r in results):
        print("Note: you were out of frame most of the time; numbers will be optimistic.")
    if not args.no_write:
        DOC_PATH.write_text(
            render_markdown(results, machine_info(settings, video), pipe.model_load_ms,
                            float(settings["process_fps"]), baseline is not None,
                            load_labels(ROOT / settings["db_path"])),
            encoding="utf-8",
        )
        print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
