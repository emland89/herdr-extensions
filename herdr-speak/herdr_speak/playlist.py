"""A pane's responses as a playlist: play one, or step to the previous or next one.

Every response Speak reads from a pane carries a track, {"pane", "index", "count"}, that
the player reports back, so "previous" and "next" know where they are. Each turn's final
text is one response (see transcripts.responses).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from . import catalog, client, herdr, paths
from . import config as settings
from .text import clean_for_speech
from .transcripts import responses

RESTART_AFTER = 3.0  # seconds into a response, "previous" restarts it instead, as music players do
LAST_TRACK = "last-track.json"  # the last response played, so previous / next work after it ends


def last_track() -> Optional[dict]:
    try:
        track = json.loads((paths.STATE_DIR / LAST_TRACK).read_text())
    except (OSError, ValueError):
        return None
    ok = isinstance(track, dict) and isinstance(track.get("pane"), str) and isinstance(track.get("index"), int)
    return track if ok else None


def _remember(track: dict) -> None:
    try:
        paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = paths.STATE_DIR / f".last-track.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(track))
        temporary.replace(paths.STATE_DIR / LAST_TRACK)
    except OSError:
        pass  # previous / next then start from the newest response


class NoTrack(LookupError):
    """There's no response at that position."""


def play(pane: str, index: int = -1, config: Optional[dict] = None, agent: Optional[dict] = None,
         queue: bool = False, source: str = "manual", prefix: str = "") -> dict:
    """Read the pane's response at `index` (negative counts from the newest); returns its track."""
    config = config or settings.load()
    agent = agent or herdr.agent_info(pane)
    items = responses(agent)
    position = index + len(items) if index < 0 else index
    if not 0 <= position < len(items):
        raise NoTrack("No response to read yet" if not items else "No response there")
    language = config.get("language") or catalog.DEFAULT_LANGUAGE
    text = clean_for_speech(items[position], language, config.get("tables", "auto"))
    if not text:
        raise NoTrack("That response has nothing to read aloud")
    track = {"pane": pane, "index": position, "count": len(items)}
    title = herdr.pane_title(pane, agent, language)
    client.speak(f"{prefix}{text}", title, config, queue=queue, source=source, track=track)
    _remember(track)
    return track


def _restart() -> None:
    client.control("seek", seconds=-1e9)


def _where(playback: dict, target: Optional[str], last: Optional[dict]) -> Optional[dict]:
    """The track to step from: what's playing, else the last one heard if it's from the target pane."""
    if playback.get("state", "idle") != "idle":
        return playback.get("track")
    last = last or last_track()
    if last and (not target or last.get("pane") == target):
        return last
    return None


def previous(target: Optional[str] = None, last: Optional[dict] = None) -> str:
    """Restart the response, or play the one before it. Returns a note for the user, or ''."""
    playback = client.playback()
    playing = playback.get("state", "idle") != "idle"
    if playing and playback.get("position", 0) > RESTART_AFTER:
        _restart()
        return ""
    track = _where(playback, target, last)
    if track:
        if track["index"] == 0:
            if playing:
                _restart()
            return "This is the first response"
        play(track["pane"], track["index"] - 1)
        return ""
    if playing:
        _restart()  # a selection or announcement: nothing before it
        return ""
    if target:
        play(target, -2)
        return ""
    return "Focus an agent pane to hear its responses"


def next_response(target: Optional[str] = None, last: Optional[dict] = None) -> str:
    """Play what's queued next, else the pane's next response. Returns a note for the user, or ''."""
    playback = client.playback()
    playing = playback.get("state", "idle") != "idle"
    if playing and playback.get("queued"):
        client.control("skip")
        return ""
    track = _where(playback, target, last)
    if track:
        try:
            play(track["pane"], track["index"] + 1)
            return ""
        except NoTrack:
            if playing:
                client.control("skip")
            return "That was the latest response"
    if playing:
        client.control("skip")
        return ""
    if target:
        play(target)
        return ""
    return "Focus an agent pane to hear its responses"
