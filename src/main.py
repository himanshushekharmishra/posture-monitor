"""Entry point: python -m src.main [--debug] [--calibrate]

No flags: runs headless with a tray icon (scripts\\run.ps1 starts it this way).
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from src.utils.env import apply_overrides, parse_env

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real-time posture monitor")
    p.add_argument("--debug", action="store_true", help="show live skeleton window")
    p.add_argument("--calibrate", action="store_true", help="record a new baseline")
    p.add_argument("--video", type=Path, metavar="PATH",
                   help="read a recorded video (e.g. data/input/test.mp4) instead of the "
                        "webcam; runs in the console and stops at the end of the video")
    p.add_argument("--label", action="store_true",
                   help="labelled session for alert precision (opens the debug window): "
                        "y/n after each alert, m for a slouch that got no alert")
    args = p.parse_args()
    if args.label:
        args.debug = True
    return args


def load_settings(path: Path = SETTINGS_PATH, overrides: bool = True) -> dict:
    """settings.json, then .env in the project root, then environment variables."""
    with path.open(encoding="utf-8") as f:
        settings = json.load(f)
    if not overrides:
        return settings
    env_file = ROOT / ".env"
    file_vars = parse_env(env_file.read_text(encoding="utf-8")) if env_file.is_file() else {}
    settings, applied = apply_overrides(settings, file_vars, os.environ)
    if applied:
        logging.getLogger("posture").info("Settings overridden: %s", ", ".join(applied))
    return settings


def setup_logging(settings: dict, to_file: bool) -> None:
    if to_file or sys.stdout is None:  # pythonw.exe has no console
        path = ROOT / settings["app_log_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=str(path), level=logging.INFO, format=LOG_FORMAT,
                            encoding="utf-8")
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=LOG_FORMAT)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    headless = not (args.debug or args.calibrate or args.video)
    setup_logging(settings, to_file=headless)
    if args.calibrate:
        from src.workflows import calibrate_flow

        ok = calibrate_flow.run(settings, root=ROOT) is not None
        raise SystemExit(0 if ok else 1)
    from src.workflows import monitor_loop

    video = args.video.resolve() if args.video else None
    if args.debug or video:
        monitor_loop.run(settings, debug=args.debug, root=ROOT, video=video, label=args.label)
    else:
        monitor_loop.run_headless(settings, root=ROOT)


if __name__ == "__main__":
    main()
