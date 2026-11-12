"""The user's Speak key bindings, read from Herdr's config.toml for the shortcut list."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paths

# (action, description), in the order the panel lists them.
ACTIONS: List[Tuple[str, str]] = [
    ("read-last", "Read the last response (again to stop)"),
    ("read-selection", "Read the selection (again to stop)"),
    ("toggle-pause", "Pause / resume"),
    ("back", "Back 5 seconds"),
    ("forward", "Forward 5 seconds"),
    ("skip", "Skip to the next response"),
    ("stop", "Stop and clear the queue"),
    ("toggle-auto", "Auto-read on / off"),
    ("panel", "This panel"),
    ("mini-player", "Mini player"),
]
_NAMES = {"comma": ",", "period": ".", "space": "Space", "minus": "-", "plus": "+", "backtick": "`"}


def herdr_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(paths.HOME / ".config")
    return Path(base) / "herdr" / "config.toml"


def _string(block: str, name: str) -> Optional[str]:
    match = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', block, re.M)
    return match.group(1) if match else None


def read_bindings(text: str, plugin_id: str) -> Tuple[str, Dict[str, str]]:
    """(prefix key, {action: key}) from config.toml text. A small parser: Python 3.9 has no tomllib."""
    prefix_match = re.search(r'^\s*\[keys\]\s*$(.*?)(?=^\s*\[)', text + "\n[", re.M | re.S)
    prefix = (_string(prefix_match.group(1), "prefix") if prefix_match else None) or "ctrl+b"
    found: Dict[str, str] = {}
    for block in re.split(r"^\s*\[\[keys\.command\]\]\s*$", text, flags=re.M)[1:]:
        block = re.split(r"^\s*\[", block, maxsplit=1, flags=re.M)[0]
        if _string(block, "type") != "plugin_action":
            continue
        command, key = _string(block, "command"), _string(block, "key")
        if command and key and command.startswith(plugin_id + "."):
            found.setdefault(command[len(plugin_id) + 1:], key)
    return prefix, found


def describe_key(key: str) -> str:
    """'prefix+shift+a' -> 'prefix Shift+A', 'prefix+comma' -> 'prefix ,'."""
    parts = key.split("+")
    lead = "prefix " if parts[0] == "prefix" else ""
    rest = parts[1:] if lead else parts
    shifted = "shift" in rest
    shown = []
    for part in rest:
        if part in _NAMES:
            shown.append(_NAMES[part])
        elif part in ("shift", "alt", "ctrl", "cmd"):
            shown.append(part.capitalize())
        elif len(part) == 1:
            shown.append(part.upper() if shifted else part)  # "prefix t", but "prefix Shift+A"
        else:
            shown.append(part)
    return lead + "+".join(shown)


def bindings(plugin_id: str = paths.PLUGIN_ID) -> Tuple[str, Dict[str, str]]:
    try:
        text = herdr_config_path().read_text()
    except OSError:
        text = ""
    return read_bindings(text, plugin_id)
