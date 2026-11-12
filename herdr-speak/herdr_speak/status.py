"""Playback status shared by the player, the panel, and Herdr's tab bar.

The player writes status.json while it runs. `statusline` is a one-line summary
that a Herdr `tab_bar_right` command entry can `cat` every second.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from . import paths

IDLE = {"state": "idle"}


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_playback() -> dict:
    """The current playback, or idle when no player is running."""
    try:
        status = json.loads(paths.STATUS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(IDLE)
    if not _alive(status.get("pid")):
        return dict(IDLE)
    return status


def write_playback(status: dict) -> None:
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    status = dict(status, pid=status.get("pid") or os.getpid(), updated=time.time())
    temporary = paths.STATUS_FILE.with_name(f".status.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(status))
    temporary.replace(paths.STATUS_FILE)


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(config: dict, playback: dict) -> str:
    from .icons import icon_set

    icons = icon_set(str(config.get("icons") or "auto"))
    state = playback.get("state", "idle")
    auto = bool(config.get("auto_read"))
    if state in ("playing", "paused", "buffering"):
        icon = icons[{"playing": "play", "paused": "pause", "buffering": "buffering"}[state]]
        title = (playback.get("title") or "Speak")[:28]
        line = f"{icon} {title} {clock(playback.get('position', 0))}"
        queued = playback.get("queued", 0)
        if queued:
            line += f" +{queued}"
        return line + (f" · {icons['auto']}" if auto else "")
    return f"{icons['speak']} auto-read" if auto else ""


def refresh(config: dict, playback: Optional[dict] = None) -> str:
    """Rewrite the tab bar line; returns it."""
    line = render(config, playback if playback is not None else read_playback())
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        current = paths.STATUSLINE_FILE.read_text()
    except FileNotFoundError:
        current = None
    if current != line + "\n":
        temporary = paths.STATUSLINE_FILE.with_name(f".statusline.{os.getpid()}.tmp")
        temporary.write_text(line + "\n")
        temporary.replace(paths.STATUSLINE_FILE)
    return line
