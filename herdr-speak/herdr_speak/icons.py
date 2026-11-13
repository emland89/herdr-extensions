"""Icons for the panel, the mini player, and the tab bar line.

"nerd" uses Nerd Font glyphs from Material Design Icons (media controls such as
rewind-5 and skip-next), which Ghostty ships built in and many terminal fonts include.
"plain" uses Unicode symbols any font has. "auto" picks "nerd" when Herdr runs inside
Ghostty. Icons take one cell each, so click targets stay aligned (wide emoji would
shift everything after them).
"""

from __future__ import annotations

import os
from typing import Dict

STYLES = ["auto", "nerd", "plain"]
STYLE_LABELS = {"auto": "Auto (Nerd Font in Ghostty)", "nerd": "Nerd Font", "plain": "Plain symbols"}

NERD: Dict[str, str] = {  # Material Design Icons in Nerd Fonts (nf-md-*)
    "speak": "\U000F057E",  # volume-high
    "play": "\U000F040A",
    "pause": "\U000F03E4",
    "stop": "\U000F04DB",
    "restart": "\U000F04AE",  # skip-previous: previous response
    "back": "\U000F11F9",  # rewind-5
    "forward": "\U000F11F8",  # fast-forward-5
    "next": "\U000F04AD",  # skip-next
    "settings": "\U000F0493",  # cog
    "close": "\U000F0156",
    "auto": "\U000F140B",  # lightning-bolt
    "voice": "\U000F036C",  # microphone
    "keys": "\U000F030C",  # keyboard
    "setup": "\U000F05B7",  # wrench
    "on": "\U000F0521",  # toggle-switch
    "off": "\U000F0A19",  # toggle-switch-off-outline
    "buffering": "\U000F0772",  # loading
    "download": "\U000F01DA",
    "ok": "\U000F012C",  # check
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
