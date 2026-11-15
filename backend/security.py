"""Keep other websites away from the local server.  Pure functions.

Two attacks matter for a server on 127.0.0.1 without a login:

- Cross-site WebSocket hijacking: any page you visit can open
  ws://127.0.0.1:8000/ws (WebSockets ignore CORS) and, for example, calibrate a
  fake baseline. The browser always sends an Origin header, so /ws accepts only
  connections whose Origin is this server itself.
- DNS rebinding: a site can make its own hostname resolve to 127.0.0.1 and then
  read /api/* as "same origin". The Host header still carries the attacker's
  hostname, so only requests addressed to an allowed host are served.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def host_name(host_header: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1', '[::1]:8000' -> '::1'."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def is_allowed_host(host_header: str | None, allowed: list[str]) -> bool:
    if not host_header:
        return False
    return host_name(host_header) in {a.lower().strip("[]") for a in allowed}


def is_same_origin(origin: str | None, host_header: str | None) -> bool:
    """True if a browser's Origin matches the Host it connected to.

    A missing Origin means a non-browser client (a script or test), which can't be
    driven by another website, so it's allowed.
    """
    if origin is None:
        return True
    if not host_header or origin == "null":
        return False
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == host_header.lower()
