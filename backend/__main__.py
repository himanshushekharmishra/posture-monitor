"""Run the web app:  python -m backend  [--host 127.0.0.1] [--port 8000]

Then open http://127.0.0.1:8000 in a browser. Keep the default host: browsers only
allow camera access on localhost or HTTPS, and the server has no authentication.
"""
import argparse
import logging
import sys

import uvicorn

from backend.app import create_app
from src.main import LOG_FORMAT, ROOT, log_overrides, read_settings


def main() -> None:
    settings, applied = read_settings()
    p = argparse.ArgumentParser(description="Posture Monitor web app")
    p.add_argument("--host", default=settings["web_host"])
    p.add_argument("--port", type=int, default=settings["web_port"])
    args = p.parse_args()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=LOG_FORMAT)
    log_overrides(applied)
    logging.getLogger("posture.web").info("Open http://%s:%d", args.host, args.port)
    uvicorn.run(create_app(settings, ROOT), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
