"""Entry point: python -m src.main [--debug] [--calibrate]"""
import argparse


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real-time posture monitor")
    p.add_argument("--debug", action="store_true", help="show live skeleton window")
    p.add_argument("--calibrate", action="store_true", help="record a new baseline")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    # Phase 1: run capture + pose with a debug overlay.
    # Later phases: calibrate_flow / monitor_loop.
    raise NotImplementedError("Phase 1: wire up workflows.monitor_loop")


if __name__ == "__main__":
    main()
