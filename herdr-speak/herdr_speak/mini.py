"""The mini player: a small split pane with playback controls that stays open while you work.

Unlike the panel popup it doesn't take over the keyboard: click its buttons, or focus
it and use the same keys as the panel. It follows the agent pane you last worked in, in
its tab: Play reads that pane's latest response, and Prev / Next step through its responses.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from typing import List, Optional, Tuple

from . import client, herdr, paths, status
from . import config as settings
from .panel import Controls, ic, track_label, use_icons
from .transcripts import SUPPORTED_AGENTS
from .ui import BOLD, DIM, GREEN, YELLOW, Line, Screen, progress_bar

STATE_FILE = "mini.json"  # the mini player's pane, so the action can toggle it


def lines(config: dict, playback: dict, width: int, controls: Controls) -> List[Line]:
    """A standard mini player: title and toggles, elapsed · progress · total, centered controls."""
    use_icons(config)
    state = playback.get("state", "idle")
    auto_on = bool(config.get("auto_read"))

    # Bare icons like the controls below, each with a cell of space around it to click.
    right = Line()
    right.add(f" {ic('auto')} auto ", DIM, "a").add(f"{ic('on')} on " if auto_on else f"{ic('off')} off ",
                                                   GREEN if auto_on else DIM, "a").add("  ")
    right.add(f" {ic('settings')} ", "", "s").add("  ")
    right.add(f" {ic('close')} ", "", "q")
    if state == "idle" and controls.target_title:
        name = controls.target_title[: max(10, width - right.width - 22)]
        title = Line().add(f" {ic('play')} ", DIM).add(name, BOLD, "space").add("  latest response", DIM, "space")
    elif state == "idle":
        title = Line().add(f" {ic('speak')} ", DIM).add("Nothing playing", DIM)
    else:
        icon = ic({"playing": "play", "paused": "pause", "buffering": "buffering"}.get(state, "play"))
        name = (playback.get("title") or "Speak")[: max(10, width - right.width - 16)]
        number = f"  {track_label(playback)}" if track_label(playback) else ""
        queued = f"  +{playback['queued']}" if playback.get("queued") else ""
        title = Line().add(f" {icon} ", GREEN if state == "playing" else YELLOW).add(name, BOLD)
        title.add(number + queued, DIM)
    title = join(title, right, width)

    position, duration = playback.get("position", 0), playback.get("duration", 0)
    elapsed = status.clock(position) if state != "idle" else "0:00"
    total = (("" if playback.get("complete", True) else "~") + status.clock(duration)) if state != "idle" else "0:00"
    bar_width = max(10, width - len(elapsed) - len(total) - 6)
    fraction = position / duration if duration and not playback.get("fallback") else 0
    progress = Line().add(f" {elapsed} ", DIM).add(progress_bar(fraction, bar_width)).add(f" {total}", DIM)

    buttons = media_row(state, ready=bool(controls.target))
    centered = Line().add(" " * max(1, (width - buttons.width) // 2))
    centered = join(centered, buttons, centered.width + buttons.width)
    return [title, progress, centered, controls.status_line()]


def media_row(state: str, ready: bool = False) -> Line:
    """Previous, back 5 s, play/pause, forward 5 s, next, stop: bare icons, as phone mini players draw them.

    Each icon is clickable with a cell of space on both sides; Ghostty also draws a Nerd
    Font icon followed by a space at double width, so they read as proper buttons.
    """
    playing = state in ("playing", "buffering")
    live = state != "idle" or ready
    controls = [("restart", "r"), ("back", "left"), ("pause" if playing else "play", "space"),
                ("forward", "right"), ("next", "n"), ("stop", "x")]
    line = Line()
    for index, (name, key) in enumerate(controls):
        if index:
            line.add("  ")
        if not live:
            style = DIM
        elif key == "space":
            style = BOLD + (GREEN if playing else "")
        else:
            style = ""
        line.add(f" {ic(name)} ", style, key)
    return line


def join(left: Line, right: Line, width: int) -> Line:
    """`left`, then `right` pushed to the right edge, keeping both lines' click targets."""
    gap = max(1, width - left.width - right.width - 1)
    left.add(" " * gap)
    left.hotspots += [(first + left.width, last + left.width, key) for first, last, key in right.hotspots]
    left.parts += right.parts
    left.width += right.width
    return left


# ---------------------------------------------------------------- where the mini player is
#
# The mini player is an ordinary Herdr pane in one tab. It records where it is in
# mini.json every few seconds; a moved pane gets a new id, but the process can still ask
# Herdr for its current pane through its original one. Callers trust the record only
# while its process is alive, so a crashed or closed mini player never leaves a stale entry.

HEARTBEAT_SECONDS = 1.0  # also how quickly the mini player notices you moved to another pane
MINI_RATIO = "0.9"  # the split ratio that leaves the mini player its few rows


def _state_path():
    return paths.STATE_DIR / STATE_FILE


def write_state(pane: str, tab: str, pid: Optional[int] = None) -> None:
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _state_path().with_name(f".mini.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"pane": pane, "tab": tab, "pid": pid or os.getpid(), "updated": time.time()}))
    temporary.replace(_state_path())


def clear_state() -> None:
    try:
        if json.loads(_state_path().read_text()).get("pid") == os.getpid():
            _state_path().unlink()
    except (OSError, ValueError):
        pass


def live_mini() -> Optional[dict]:
    """{"pane", "tab", "pid"} of the running mini player, or None."""
    try:
        state = json.loads(_state_path().read_text())
        pid = int(state["pid"])
        command = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return state if "speak.py mini" in command and state.get("pane") else None


def current_location() -> Tuple[str, str]:
    """This process's pane and tab, also after Herdr moved the pane."""
    pane = herdr.run_json("pane", "current", "--current").get("pane", {})
    return pane["pane_id"], pane["tab_id"]


def focused_location() -> Tuple[str, str]:
    """The pane and tab the user is looking at."""
    context = herdr.invocation_context()
    pane = context.get("focused_pane_id")
    panes = herdr.run_json("pane", "list").get("panes", [])
    match = next((p for p in panes if p.get("pane_id") == pane), None) or next((p for p in panes if p.get("focused")), None)
    if not match:
        raise RuntimeError("No focused pane")
    return match["pane_id"], match["tab_id"]


def pick_target(panes: List[dict], mini_pane: str, tab: str, current: Optional[str]) -> Optional[dict]:
    """The agent pane the mini player plays: the focused one in its tab, else the one it had, else the first."""
    agents = [p for p in panes if p.get("tab_id") == tab and p.get("pane_id") != mini_pane
              and p.get("agent") in SUPPORTED_AGENTS]
    return (next((p for p in agents if p.get("focused")), None)
            or next((p for p in agents if p.get("pane_id") == current), None)
            or (agents[0] if agents else None))


def update_target(controls: Controls, mini_pane: str, tab: str, language: Optional[str]) -> None:
    panes = herdr.run_json("pane", "list").get("panes", [])
    chosen = pick_target(panes, mini_pane, tab, controls.target)
    if chosen is None:
        controls.target, controls.target_title = None, ""
    elif chosen["pane_id"] != controls.target or not controls.target_title:
        controls.target = chosen["pane_id"]
        controls.target_title = herdr.pane_title(chosen["pane_id"], chosen, language)


def move_to(mini: dict, pane: str, tab: str) -> None:
    result = herdr.run_json("pane", "move", mini["pane"], "--tab", tab, "--split", "down", "--target-pane", pane,
                            "--ratio", MINI_RATIO, "--no-focus")
    moved = (result.get("move_result") or {}).get("pane") or {}
    if moved.get("pane_id"):
        write_state(moved["pane_id"], tab, int(mini["pid"]))


# ---------------------------------------------------------------- entry points


def run(screen_factory=Screen) -> int:
    controls = Controls()
    last_beat = 0.0
    try:
        client.warm(settings.load())
    except (OSError, RuntimeError):
        pass
    try:
        with screen_factory() as screen:
            while True:
                config = settings.load()
                if time.time() - last_beat > HEARTBEAT_SECONDS:
                    last_beat = time.time()
                    try:
                        here = current_location()
                        write_state(*here)
                        update_target(controls, *here, config.get("language"))
                    except (RuntimeError, OSError, KeyError, ValueError, subprocess.SubprocessError):
                        pass  # outside Herdr (tests) or Herdr busy: try again next beat
                width, _ = screen.size()
                screen.draw(lines(config, client.playback(), width, controls))
                for event in screen.events(0.5):
                    key = event.key
                    if key in ("q", "escape"):
                        return 0
                    if controls.playback_key(key):
                        continue
                    if key == "a":
                        config["auto_read"] = not config.get("auto_read")
                        settings.save(config)
                        status.refresh(config)
                    elif key == "s":
                        try:
                            herdr.open_panel(controls.target, controls.target_title)
                        except RuntimeError as error:
                            controls.note(str(error))
    finally:
        clear_state()


def toggle() -> None:
    """Open the mini player below the focused pane; bring it here from another tab; close it when it's here."""
    mini = live_mini()
    pane, tab = focused_location()
    if mini and mini.get("tab") == tab:
        herdr.run_json("pane", "close", mini["pane"])
        return
    if mini:
        move_to(mini, pane, tab)
        return
    result = herdr.run_json("plugin", "pane", "open", "--plugin", paths.PLUGIN_ID, "--entrypoint", "mini",
                            "--placement", "split", "--direction", "down", "--target-pane", pane)
    new_pane = _find_pane_id(result)
    if new_pane:
        herdr.resize_to_rows(new_pane, 3)


def follow(config: dict) -> None:
    """Event hook for tab and workspace focus: move the mini player to the tab now in view."""
    if not config.get("mini_follow"):
        return
    mini = live_mini()
    if not mini:
        return
    # Rapid switching starts one hook per switch; serialize them and act on where the user is now.
    with open(paths.STATE_DIR / "mini.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        mini = live_mini()
        panes = herdr.run_json("pane", "list").get("panes", [])
        focused = next((p for p in panes if p.get("focused")), None)
        if not mini or not focused or focused["pane_id"] == mini["pane"] or focused["tab_id"] == mini.get("tab"):
            return
        move_to(mini, focused["pane_id"], focused["tab_id"])


def _find_pane_id(result) -> Optional[str]:
    stack = [result]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("pane_id"), str):
                return item["pane_id"]
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None
