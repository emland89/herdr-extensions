"""Add Speak's key bindings and tab bar indicator to Herdr's config.toml, or remove them.

Herdr plugins can't declare key bindings, so setup writes them into the user's config:
one marked block at the end, only for keys that are free (not a Herdr default, not used
in the config) and actions not already bound. The config is backed up first and Herdr's
reload diagnostics decide: on any problem the backup is restored.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paths
from .shortcuts import herdr_config_path

BEGIN = "# >>> Speak (emilapps.speak) key bindings: managed by the plugin; remove with `speak.py unbind` >>>"
END = "# <<< Speak key bindings <<<"

# (key, action, description)
DEFAULT_BINDINGS: List[Tuple[str, str, str]] = [
    ("prefix+t", "read-last", "Speak: read last response (again to stop)"),
    ("prefix+a", "read-selection", "Speak: read selection (again to stop)"),
    ("prefix+shift+a", "panel", "Speak: player and settings"),
    ("prefix+m", "mini-player", "Speak: mini player"),
    ("prefix+space", "toggle-pause", "Speak: pause / resume"),
    ("prefix+comma", "back", "Speak: back 5 seconds"),
    ("prefix+period", "forward", "Speak: forward 5 seconds"),
]

# Herdr 0.9.5's default prefix bindings (config reference), so Speak never shadows one.
HERDR_DEFAULT_KEYS = {
    "prefix+?", "prefix+s", "prefix+shift+n", "prefix+shift+g", "prefix+shift+w", "prefix+shift+d", "prefix+w",
    "prefix+g", "prefix+q", "prefix+shift+r", "prefix+o", "prefix+c", "prefix+shift+t", "prefix+p", "prefix+n",
    "prefix+shift+x", "prefix+shift+p", "prefix+e", "prefix+[", "prefix+h", "prefix+j", "prefix+k", "prefix+l",
    "prefix+shift+h", "prefix+shift+j", "prefix+shift+k", "prefix+shift+l", "prefix+tab", "prefix+shift+tab",
    "prefix+v", "prefix+minus", "prefix+x", "prefix+z", "prefix+r", "prefix+b",
} | {f"prefix+{n}" for n in range(1, 10)} | {f"prefix+shift+{n}" for n in range(1, 10)}


def statusline_command() -> str:
    return f'cat \\"{paths.STATUSLINE_FILE}\\" 2>/dev/null'


def _without_block(text: str) -> str:
    return re.sub(rf"\n*{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "\n", text, flags=re.S).rstrip("\n") + "\n"


def used_keys(text: str) -> set:
    """Every key string assigned anywhere in the config: custom commands and [keys] overrides."""
    keys = set(re.findall(r'^\s*key\s*=\s*"([^"]+)"', text, re.M))
    keys_table = re.search(r"^\s*\[keys\]\s*$(.*?)(?=^\s*\[)", text + "\n[", re.M | re.S)
    if keys_table:
        keys |= set(re.findall(r'"([^"]+)"', keys_table.group(1)))
    return {key.strip().lower() for key in keys}


def bound_actions(text: str, plugin_id: str) -> set:
    return set(re.findall(rf'^\s*command\s*=\s*"{re.escape(plugin_id)}\.([\w:-]+)"', text, re.M))


def plan(text: str, plugin_id: str = paths.PLUGIN_ID) -> Tuple[List[Tuple[str, str, str]], List[str], bool]:
    """(bindings to add, notes about skipped ones, whether to add the tab bar entry).

    Judged against the config without Speak's own block and indicator, so re-running
    reproduces the same result.
    """
    base = _remove_tab_bar_entry(_without_block(text))
    taken, already = used_keys(base) | HERDR_DEFAULT_KEYS, bound_actions(base, plugin_id)
    add, notes = [], []
    for key, action, description in DEFAULT_BINDINGS:
        if action in already:
            continue  # the user bound it themselves
        if key in taken:
            notes.append(f"{key} is already used, so {action} has no key")
            continue
        add.append((key, action, description))
    tab_bar = not re.search(r"^\s*tab_bar_right\s*=", base, re.M)
    if not tab_bar and "statusline" not in base:
        notes.append("You already have a tab_bar_right list; add Speak's entry from the README to see its indicator")
    return add, notes, tab_bar


def render_block(add: List[Tuple[str, str, str]], tab_bar: bool, has_ui_table: bool,
                 plugin_id: str = paths.PLUGIN_ID) -> str:
    lines = [BEGIN]
    for key, action, description in add:
        lines += ["[[keys.command]]", f'key = "{key}"', 'type = "plugin_action"',
                  f'command = "{plugin_id}.{action}"', f'description = "{description}"', ""]
    if tab_bar and not has_ui_table:
        lines += ["[ui]", "tab_bar_right = [",
                  f'  {{ type = "command", command = "{statusline_command()}", interval_seconds = 1, timeout_seconds = 1 }},',
                  "]", ""]
    lines.append(END)
    return "\n".join(lines) + "\n"


def with_tab_bar_in_ui(text: str) -> str:
    """Insert the indicator into an existing [ui] table (TOML can't define [ui] twice)."""
    entry = (f'tab_bar_right = [  # Speak (emilapps.speak) indicator; `speak.py unbind` removes it\n'
             f'  {{ type = "command", command = "{statusline_command()}", interval_seconds = 1, timeout_seconds = 1 }},\n'
             f']  # end Speak indicator\n')
    return re.sub(r"^(\s*\[ui\]\s*\n)", lambda m: m.group(1) + entry, text, count=1, flags=re.M)


def _remove_tab_bar_entry(text: str) -> str:
    return re.sub(r"^tab_bar_right = \[  # Speak \(emilapps\.speak\).*?\]  # end Speak indicator\n", "", text,
                  flags=re.M | re.S)


def reload_herdr() -> Optional[List[str]]:
    """Reload Herdr's config; returns its diagnostics, or None when no server is running."""
    try:
        result = subprocess.run([os.environ.get("HERDR_BIN_PATH") or "herdr", "server", "reload-config"],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return [str(d) for d in json.loads(result.stdout).get("result", {}).get("diagnostics", [])]
    except ValueError:
        return None


def bind(config_path: Optional[Path] = None) -> Dict[str, object]:
    """Add the bindings that are free; returns what happened."""
    path = config_path or herdr_config_path()
    text = path.read_text() if path.exists() else ""
    add, notes, tab_bar = plan(text)
    base = _remove_tab_bar_entry(_without_block(text)) if text else ""
    if add or tab_bar:
        has_ui = bool(re.search(r"^\s*\[ui\]\s*$", base, re.M))
        new = (with_tab_bar_in_ui(base) if tab_bar and has_ui else base).rstrip("\n")
        new = (new + "\n\n" if new else "") + render_block(add, tab_bar, has_ui)
    else:
        new = base
    if new == text:
        return {"changed": False, "added": [], "notes": notes}
    backup = path.with_name(path.name + ".speak-backup")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text(new)
    diagnostics = reload_herdr()
    if diagnostics:
        if backup.exists():
            shutil.copy2(backup, path)
        else:
            path.unlink()
        reload_herdr()
        return {"changed": False, "added": [], "notes": notes + [f"Herdr rejected the change: {diagnostics[0]}"]}
    return {"changed": True, "added": [key for key, _, _ in add], "tab_bar": tab_bar, "notes": notes,
            "backup": str(backup) if backup.exists() else None}


def unbind(config_path: Optional[Path] = None) -> bool:
    path = config_path or herdr_config_path()
    if not path.exists():
        return False
    text = path.read_text()
    new = _remove_tab_bar_entry(_without_block(text))
    if new == text:
        return False
    shutil.copy2(path, path.with_name(path.name + ".speak-backup"))
    path.write_text(new)
    reload_herdr()
    return True


def managed(config_path: Optional[Path] = None) -> bool:
    path = config_path or herdr_config_path()
    return path.exists() and BEGIN in path.read_text()
