"""Desktop notifications via plyer, text from messages/alerts.json.  Phase 3."""
from __future__ import annotations

import json
from pathlib import Path

APP_NAME = "Posture Monitor"


def notify(title: str, message: str, timeout: int = 10) -> None:
    """Show a desktop notification. Never raises: a failed toast must not stop monitoring."""
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name=APP_NAME, timeout=timeout)
    except Exception as e:  # plyer backends raise a variety of errors
        print(f"Notification failed ({e!r}): {title}: {message}")


class AlertNotifier:
    """Sends posture alerts, cycling through the message variants in turn."""

    def __init__(self, alerts_path: Path, timeout: int) -> None:
        data = json.loads(alerts_path.read_text(encoding="utf-8"))
        self.title: str = data["title"]
        self.variants: list[str] = list(data["variants"]) or ["Check your posture."]
        self.timeout = timeout
        self._next = 0

    def next_message(self) -> str:
        msg = self.variants[self._next % len(self.variants)]
        self._next += 1
        return msg

    def alert(self) -> str:
        msg = self.next_message()
        notify(self.title, msg, self.timeout)
        return msg
