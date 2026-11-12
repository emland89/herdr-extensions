"""A tiny terminal UI layer for the panel and the mini player: drawing, keys, and mouse clicks.

Lines are built from segments; a segment with a key becomes a clickable hotspot that
sends that key, so every button also has a keyboard shortcut.
"""

from __future__ import annotations

import os
import re
import select
import sys
import termios
import tty
from typing import List, Optional, Tuple

BOLD, DIM, CYAN, GREEN, YELLOW, RED, RESET = "\x1b[1m", "\x1b[2m", "\x1b[36m", "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[0m"
REVERSE = "\x1b[7m"

# SGR mouse reporting: button presses arrive as ESC [ < button ; column ; row M
_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_KEYS = {"\x1b[D": "left", "\x1b[C": "right", "\x1b[A": "up", "\x1b[B": "down", "\x1bOD": "left", "\x1bOC": "right",
         "\x1b[Z": "backtab"}


class Event:
    """A key ("a", "A", "space", "left", "escape", ...) or a click resolved to its hotspot's key."""

    def __init__(self, key: str, backwards: bool = False, clicked: bool = False):
        self.key = key
        self.backwards = backwards  # Shift+letter or right-click: cycle the other way
        self.clicked = clicked

    def __repr__(self) -> str:
        return f"Event({self.key!r}, backwards={self.backwards}, clicked={self.clicked})"


def parse_input(data: str) -> List[Tuple[str, object]]:
    """Split raw terminal input into ("key", name) and ("click", (button, column, row)) items."""
    items: List[Tuple[str, object]] = []
    index = 0
    while index < len(data):
        mouse = _MOUSE.match(data, index)
        if mouse:
            button, column, row, kind = int(mouse.group(1)), int(mouse.group(2)), int(mouse.group(3)), mouse.group(4)
            if kind == "M" and button in (0, 2):  # left or right press; ignore releases, motion, wheel
                items.append(("click", (button, column, row)))
            index = mouse.end()
            continue
        sequence = next((s for s in _KEYS if data.startswith(s, index)), None)
        if sequence:
            items.append(("key", _KEYS[sequence]))
            index += len(sequence)
            continue
        if data.startswith("\x1b[", index) or data.startswith("\x1bO", index):
            # Another escape sequence (function keys, focus events): skip it.
            match = re.compile(r"\x1b[\[O][0-9;?]*[A-Za-z~]").match(data, index)
            index = match.end() if match else index + 2
            continue
        char = data[index]
        names = {"\x1b": "escape", "\x03": "escape", " ": "space", "\r": "enter", "\n": "enter", "\t": "tab"}
        items.append(("key", names.get(char, char)))
        index += 1
    return items


class Line:
    """One screen line built from styled segments; segments with a key are clickable."""

    def __init__(self):
        self.parts: List[str] = []
        self.width = 0
        self.hotspots: List[Tuple[int, int, str]] = []  # (first column, last column, key), 1-based

    def add(self, text: str, style: str = "", key: Optional[str] = None) -> Line:
        if key is not None and text:
            self.hotspots.append((self.width + 1, self.width + len(text), key))
        self.parts.append(f"{style}{text}{RESET}" if style else text)
        self.width += len(text)
        return self

    def render(self) -> str:
        return "".join(self.parts)


class Screen:
    """Raw-mode terminal with mouse reporting; restores the terminal on exit."""

    def __init__(self, mouse: bool = True):
        self.fd = sys.stdin.fileno()
        self.mouse = mouse
        self.saved = None
        self.hotspots: List[Tuple[int, int, int, str]] = []  # (row, first column, last column, key)

    def __enter__(self) -> Screen:
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?25l\x1b[2J")  # hide the cursor, clear once
        if self.mouse:
            sys.stdout.write("\x1b[?1000h\x1b[?1006h")  # button events, SGR coordinates
        sys.stdout.flush()
        return self

    def __exit__(self, *exc) -> None:
        if self.mouse:
            sys.stdout.write("\x1b[?1006l\x1b[?1000l")
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    @staticmethod
    def size() -> Tuple[int, int]:
        try:
            columns, rows = os.get_terminal_size()
        except OSError:
            columns, rows = 0, 0
        return columns or 80, rows or 24

    def draw(self, lines: List[Line]) -> None:
        _, rows = self.size()
        lines = lines[:rows]
        self.hotspots = [(row, first, last, key) for row, line in enumerate(lines, 1) for first, last, key in line.hotspots]
        sys.stdout.write("\x1b[H" + "".join(line.render() + "\x1b[K\r\n" for line in lines[:-1])
                         + (lines[-1].render() + "\x1b[K" if lines else "") + "\x1b[J")
        sys.stdout.flush()

    def hit(self, column: int, row: int) -> Optional[str]:
        for hot_row, first, last, key in self.hotspots:
            if hot_row == row and first <= column <= last:
                return key
        return None

    def events(self, timeout: float) -> List[Event]:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        data = os.read(self.fd, 1024).decode(errors="ignore")
        events = []
        for kind, value in parse_input(data):
            if kind == "click":
                button, column, row = value  # type: ignore[misc]
                key = self.hit(column, row)
                if key:
                    events.append(Event(key, backwards=button == 2, clicked=True))
            else:
                key = str(value)
                backwards = len(key) == 1 and key.isalpha() and key.isupper()
                events.append(Event(key.lower() if backwards else key, backwards=backwards))
        return events


def progress_bar(fraction: float, width: int) -> str:
    width = max(width, 4)
    filled = int(max(0.0, min(fraction, 1.0)) * width)
    return f"{CYAN}{'━' * filled}{RESET}{DIM}{'─' * (width - filled)}{RESET}"


def button(line: Line, label: str, key: str, style: str = REVERSE) -> Line:
    return line.add(f" {label} ", style, key).add(" ")
