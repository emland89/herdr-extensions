"""Auto-read: speak a response when its agent finishes a turn.

Runs from the `pane.agent_status_changed` event hook. Herdr starts a new process
for every status change of every pane, so this returns at once while auto-read
is off and keeps its per-pane memory in a small locked JSON file.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import time
from contextlib import contextmanager
from typing import Optional, Tuple

from . import catalog, client, herdr, paths
from .text import clean_for_speech
from .transcripts import SUPPORTED_AGENTS, last_response


def parse_status_event(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """(pane_id, agent_status) from HERDR_PLUGIN_EVENT_JSON, wherever they are nested."""
    try:
        event = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None, None
    stack = [event]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if "pane_id" in item and "agent_status" in item:
                return item["pane_id"], item["agent_status"]
            stack.extend(item.values())
    return None, None


def should_read(previous: Optional[str], current: str) -> bool:
    # A finished turn: working -> idle (pane in view) or working -> done (not yet seen).
    return previous == "working" and current in ("idle", "done")


def in_scope(scope: Optional[str], focused: bool) -> bool:
    return not ((scope == "background" and focused) or (scope == "focused" and not focused))


@contextmanager
def _pane_state():
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.STATE_DIR / "panes.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            panes = json.loads(paths.PANES_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            panes = {}
        yield panes
        paths.PANES_FILE.write_text(json.dumps(panes))


def remember(pane: str, **values) -> dict:
    """Merge values into the pane's saved state; returns the state before the change."""
    with _pane_state() as panes:
        before = dict(panes.get(pane, {}))
        panes.setdefault(pane, {}).update(values)
    return before


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()  # tells responses apart; not a security use


def current_digest(agent: dict, language: Optional[str]) -> Optional[str]:
    try:
        return digest_of(clean_for_speech(last_response(agent) or "", language or catalog.DEFAULT_LANGUAGE))
    except (RuntimeError, OSError):
        return None


def handle_event(config: dict, raw_event: str) -> None:
    if not config.get("auto_read"):
        return
    pane, current = parse_status_event(raw_event)
    if not pane or not current:
        return
    before = remember(pane, status=current)
    previous = before.get("status")
    language = config.get("language")
    if current == "working" and previous != "working":
        # Remember the response on screen when the turn starts, so a transcript that
        # hasn't caught up yet isn't mistaken for the new reply.
        agent = herdr.agent_info(pane)
        if agent.get("agent") in SUPPORTED_AGENTS:
            remember(pane, before_turn=current_digest(agent, language))
            if in_scope(config.get("auto_panes"), bool(agent.get("focused"))):
                client.warm(config)  # the voice is ready by the time the agent finishes
        return
    finished = should_read(previous, current)
    blocked = current == "blocked" and previous != "blocked" and config.get("announce_blocked")
    if not (finished or blocked):
        return

    agent = herdr.agent_info(pane)
    if agent.get("agent") not in SUPPORTED_AGENTS or not in_scope(config.get("auto_panes"), bool(agent.get("focused"))):
        return
    title = herdr.pane_title(pane, agent, language)
    if blocked:
        client.speak(f"{title} {catalog.language(language)['needs_input']}", title, config, queue=True, source="auto")
        return

    # The transcript can trail the status change; wait for a response that is neither
    # the one from before the turn nor one already spoken.
    stale = {before.get("before_turn"), before.get("spoken")}
    for _ in range(6):
        spoken = clean_for_speech(last_response(agent) or "", language)
        digest = digest_of(spoken)
        if spoken and digest not in stale:
            break
        time.sleep(0.5)
    else:
        return
    announced = f"{title}.\n\n{spoken}" if config.get("announce", True) else spoken
    client.speak(announced, title, config, queue=True, source="auto")
    remember(pane, spoken=digest)  # only once it was handed to the player
