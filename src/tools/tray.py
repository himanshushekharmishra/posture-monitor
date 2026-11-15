"""pystray tray icon: Pause / Recalibrate / Quit.  Phase 4."""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from src.schemas.models import MonitorStatus, PostureState

APP_TITLE = "Posture Monitor"
ICON_SIZE = 64
STATE_RGB = {
    PostureState.AWAY: (150, 150, 150),
    PostureState.GOOD: (40, 180, 70),
    PostureState.SLOUCHING: (245, 170, 30),
    PostureState.ALERTED: (220, 50, 50),
}
PAUSED_RGB = (90, 90, 90)


@lru_cache(maxsize=None)
def make_icon_image(state: PostureState, paused: bool) -> Image.Image:
    """A filled circle in the state colour; paused shows grey with two bars."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, ICON_SIZE - 4, ICON_SIZE - 4), fill=PAUSED_RGB if paused else STATE_RGB[state])
    if paused:
        for x in (22, 36):
            d.rectangle((x, 18, x + 6, ICON_SIZE - 18), fill=(255, 255, 255))
    return img


def status_text(s: MonitorStatus) -> str:
    if s.paused:
        main = "Paused (camera off)"
    elif s.note:
        main = s.note.capitalize()
    else:
        main = s.state.value.capitalize()
    return f"{main} - {s.alerts_today} alert{'s' if s.alerts_today != 1 else ''} today"


class TrayApp:
    def __init__(
        self,
        on_toggle_pause: Callable[[], None],
        on_recalibrate: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._status = MonitorStatus()
        self._on_toggle_pause = on_toggle_pause
        self._on_recalibrate = on_recalibrate
        self._on_quit = on_quit
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: status_text(self._status), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "Resume" if self._status.paused else "Pause", self._pause_clicked
            ),
            pystray.MenuItem("Recalibrate", self._recalibrate_clicked),
            pystray.MenuItem("Quit", self._quit_clicked),
        )
        self._icon = pystray.Icon(
            "posture-monitor", make_icon_image(PostureState.AWAY, False),
            f"{APP_TITLE}: starting", menu,
        )

    def _pause_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_toggle_pause()

    def _recalibrate_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_recalibrate()

    def _quit_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_quit()
        self.stop()

    def set_status(self, status: MonitorStatus) -> None:
        """Called from the monitor thread whenever the status changes."""
        self._status = status
        self._icon.icon = make_icon_image(status.state, status.paused)
        self._icon.title = f"{APP_TITLE}: {status_text(status)}"[:127]
        self._icon.update_menu()

    def run(self) -> None:
        """Blocks until stop() is called. Must run on the main thread."""
        self._icon.run()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # stopping before run() started is harmless
            pass
