"""Icons for the panel, the mini player, and the tab bar line.

"nerd" uses Nerd Font (Font Awesome) glyphs, which Ghostty ships built in and many
terminal fonts include. "plain" uses Unicode symbols any font has. "auto" picks
"nerd" when Herdr runs inside Ghostty. Every icon is one cell wide in both sets, so
click targets stay aligned (wide emoji would shift everything after them).
"""

from __future__ import annotations

import os
from typing import Dict

STYLES = ["auto", "nerd", "plain"]
STYLE_LABELS = {"auto": "Auto (Nerd Font in Ghostty)", "nerd": "Nerd Font", "plain": "Plain symbols"}

NERD: Dict[str, str] = {
    "speak": "\uf028",  # volume-up
    "play": "\uf04b",
    "pause": "\uf04c",
    "stop": "\uf04d",
    "restart": "\uf048",  # step-backward
    "back": "\uf04a",  # backward
    "forward": "\uf04e",
    "next": "\uf051",  # step-forward
    "settings": "\uf013",  # cog
    "close": "\uf00d",  # times
    "auto": "\uf0e7",  # bolt
    "voice": "\uf130",  # microphone
    "keys": "\uf11c",  # keyboard
    "setup": "\uf0ad",  # wrench
    "on": "\uf205",  # toggle-on
    "off": "\uf204",  # toggle-off
    "buffering": "\uf110",  # spinner
    "download": "\uf019",
    "ok": "\uf00c",  # check
}
PLAIN: Dict[str, str] = {
    "speak": "♪", "play": "▶", "pause": "‖", "stop": "■", "restart": "|«", "back": "«", "forward": "»", "next": "»|",
    "settings": "≡", "close": "×", "auto": "↻", "voice": "∿", "keys": "⌨", "setup": "⚒", "on": "●", "off": "○",
    "buffering": "…", "download": "↓", "ok": "✓",
}


def resolve(style: str) -> str:
    if style in ("nerd", "plain"):
        return style
    return "nerd" if os.environ.get("GHOSTTY_RESOURCES_DIR") or os.environ.get("TERM_PROGRAM") == "ghostty" else "plain"


def icon_set(style: str) -> Dict[str, str]:
    return NERD if resolve(style) == "nerd" else PLAIN
