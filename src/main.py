"""Entry point: python -m src.main [--debug] [--calibrate]"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real-time posture monitor")
    p.add_argument("--debug", action="store_true", help="show live skeleton window")
    p.add_argument("--calibrate", action="store_true", help="record a new baseline")
    return p.parse_args()


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    if args.calibrate:
        from src.workflows import calibrate_flow

        ok = calibrate_flow.run(settings, root=ROOT) is not None
        raise SystemExit(0 if ok else 1)
    from src.workflows import monitor_loop

    monitor_loop.run(settings, debug=args.debug, root=ROOT)


if __name__ == "__main__":
    main()
