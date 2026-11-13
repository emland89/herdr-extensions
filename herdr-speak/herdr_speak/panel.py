"""The Speak panel: a tabbed popup for playback, settings, shortcuts, and setup.

Tabs: Player, Auto-read, Voice, Shortcuts, Setup. Everything is clickable (left-click;
right-click steps a setting backwards) and has a key; the letter keys work on every tab.
Choices with several options open as dropdowns. Plain ANSI with the standard library,
so it works before any setup.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, Tuple

from . import __version__, catalog, client, herdr, icons, paths, playlist, runtime, shortcuts, status
from . import config as settings
from .ui import BOLD, CYAN, DIM, GREEN, RED, REVERSE, YELLOW, Line, Screen, button, progress_bar

SEEK_SECONDS = 5
TABS = ["Player", "Auto-read", "Voice", "Shortcuts", "Setup"]
TAB_ICONS = ["speak", "auto", "voice", "keys", "setup"]
_ICONS = dict(icons.PLAIN)  # the set in use; use_icons() switches it for each frame


def use_icons(config: dict) -> None:
    _ICONS.clear()
    _ICONS.update(icons.icon_set(str(config.get("icons") or "auto")))


def ic(name: str) -> str:
    return _ICONS[name]
TAB_FILE = "panel-tab"  # the last tab, so the panel reopens where you left it
HEADING = "\x1b[1;36m"
LABEL_WIDTH = 14  # settings labels form one column
FIELD_WIDTH = 30  # dropdown fields are this wide
HINT_COLUMN = 64  # key hints after checkboxes line up here

# Keys that work on every tab, for the Shortcuts tab.
PANEL_KEYS = [
    ("1-5, Tab", "Switch tab"), ("space", "Pause / resume, or play the pane"), ("← →", "Back / forward 5 seconds"),
    ("r  n  x", "Previous / next response / stop"), ("t", "Test the voice"), ("a f m b", "Auto-read settings"),
    ("l v s o", "Language, voice, speed, model"), ("p", "Mini player follows you between tabs"), ("k", "Media keys"),
    ("↑ ↓ Enter", "Choose in an open dropdown"),
    ("i", "Install or repair the voice"), ("q, Esc", "Close (Esc closes a dropdown first)"),
]


def cycle(options: list, current, step: int = 1):
    if not options:
        return current
    index = options.index(current) if current in options else -1
    return options[(index + step) % len(options)]


def voice_choices(config: dict) -> List[Tuple[str, str]]:
    choices = []
    if settings.kokoro_ready(config):
        choices += [("kokoro", name) for name in catalog.kokoro_voices_for(config["language"])]
    return choices + [("say", name) for name in catalog.say_voices_for(config["language"])]


def dropdown_options(name: str) -> List[Tuple[str, str]]:
    if name == "language":
        return [(code, info["name"]) for code, info in catalog.LANGUAGES.items()]
    if name == "auto_panes":
        return [(value, settings.AUTO_PANES_LABELS[value]) for value in settings.AUTO_PANES]
    if name == "model":
        return [("full", "Full (325 MB, best)"), ("small", "Small (92 MB)")]
    if name == "icons":
        return [(style, icons.STYLE_LABELS[style]) for style in icons.STYLES]
    return []


class Controls:
    """Playback keys and messages shared by the panel and the mini player."""

    def __init__(self):
        self.message = ""
        self.busy = ""
        self.target: Optional[str] = None  # the agent pane that play, previous, and next use when idle
        self.target_title = ""

    def note(self, message: str, style: str = DIM) -> None:
        self.message = f"{style}{message}"

    def run(self, command: str, **arguments) -> None:
        try:
            if not client.control(command, **arguments):
                self.note("Nothing is playing")
        except (OSError, RuntimeError) as error:  # the player can stop between status and command
            self.note(str(error), YELLOW)

    def in_background(self, label: str, work: Callable[[], object]) -> None:
        """Run work off the drawing loop; a string it returns is shown as a note."""
        self.busy = label

        def run() -> None:
            try:
                result = work()
                self.message = ""
                if isinstance(result, str) and result:
                    self.note(result)
            except playlist.NoTrack as error:
                self.note(str(error))
            except Exception as error:  # shown in the panel
                self.note(str(error), RED)
            finally:
                self.busy = ""

        threading.Thread(target=run, daemon=True).start()

    def playback_key(self, key: str) -> bool:
        """Handle a playback key; False when the key isn't one."""
        if key == "space":
            if self.target and client.playback().get("state", "idle") == "idle":
                self.in_background("Loading", lambda: playlist.play(self.target))
            else:
                self.run("toggle-pause")
        elif key in ("left", ","):
            self.run("seek", seconds=-SEEK_SECONDS)
        elif key in ("right", "."):
            self.run("seek", seconds=SEEK_SECONDS)
        elif key == "n":
            self.in_background("Loading", lambda: playlist.next_response(self.target))
        elif key == "r":
            self.in_background("Loading", lambda: playlist.previous(self.target))
        elif key == "x":
            try:
                client.stop()
            except (OSError, RuntimeError) as error:
                self.note(str(error), YELLOW)
        else:
            return False
        return True

    def status_line(self) -> Line:
        text = f"{self.busy}…" if self.busy else self.message
        return Line().add(f"  {text}", DIM if self.busy else "")


# ---------------------------------------------------------------- shared widgets


def track_label(playback: dict) -> str:
    """'3/5' for a pane response: which response of the pane's turns this is."""
    track = playback.get("track")
    return f"{track['index'] + 1}/{track['count']}" if isinstance(track, dict) and "index" in track else ""


def player_lines(playback: dict, width: int, indent: str = "  ", ready: str = "") -> List[Line]:
    """Title with the time at the right edge, then a full-width progress bar.

    `ready`: the pane that Play would read when nothing is playing.
    """
    state = playback.get("state", "idle")
    if state == "idle":
        head = Line().add(f"{indent}{ic('play')} {ready}", BOLD).add("  latest response", DIM) if ready else \
            Line().add(f"{indent}Nothing playing", DIM)
        return [head, Line().add(f"{indent}{progress_bar(0, width - 2 * len(indent))}")]
    icon = ic({"playing": "play", "paused": "pause", "buffering": "buffering"}.get(state, "play"))
    position, duration = playback.get("position", 0), playback.get("duration", 0)
    right = ""
    if not playback.get("fallback"):
        total = ("" if playback.get("complete", True) else "~") + status.clock(duration)
        queued = playback.get("queued", 0)
        right = f"{status.clock(position)} / {total}" + (f"   +{queued} queued" if queued else "")
        right = (f"{track_label(playback)}   " if track_label(playback) else "") + right
    title = (playback.get("title") or "Speak")[: max(10, width - len(right) - len(indent) * 2 - 4)]
    head = Line().add(f"{indent}{icon} {title}", BOLD)
    head.add(" " * max(1, width - head.width - len(right) - len(indent))).add(right, DIM)
    if playback.get("fallback"):
        return [head, Line().add(f"{indent}macOS speech without the voice runtime: pause and stop only", DIM)]
    bar_width = max(10, width - 2 * len(indent))
    return [head, Line().add(indent).add(progress_bar(position / duration if duration else 0, bar_width))]


def transport(state: str, indent: str = "  ", labels: bool = True, ready: bool = False) -> Line:
    """Media controls in the usual order: previous, back, play/pause, forward, next, stop.

    The middle button shows what it will do: pause while playing, play otherwise.
    `ready`: nothing plays but there's a pane to play, so the buttons are live.
    """
    playing = state in ("playing", "buffering")
    middle = (ic("pause"), "Pause") if playing else (ic("play"), "Play")
    controls = [(ic("restart"), "Prev", "r"), (ic("back"), "5s", "left"), (middle[0], middle[1], "space"),
                (ic("forward"), "5s", "right"), (ic("next"), "Next", "n"), (ic("stop"), "Stop", "x")]
    line = Line().add(indent)
    idle = state == "idle" and not ready
    for icon, label, key in controls:
        text = f"{icon} {label}" if labels and label else icon
        if key == "space":
            text = f" {text} "  # the main button is wider, as in most players
        button(line, text, key, style=REVERSE if not idle else DIM + REVERSE)
    return line


def heading(text: str, width: int) -> Line:
    """'── TITLE ─────────' across the content width."""
    label = f" {text.upper()} "
    return Line().add("  ──", DIM).add(label, HEADING).add("─" * max(2, width - len(label) - 6), DIM)


def field(label: str, key: Optional[str] = None) -> Line:
    return Line().add(f"  {label:<{LABEL_WIDTH}}", "", key)


def checkbox(label: str, value: bool, key: str, hint: str = "") -> Line:
    line = Line().add("  ")
    line.add(ic("on") if value else ic("off"), GREEN if value else DIM, key).add(f" {label}", "", key)
    return line.add(" " * max(2, HINT_COLUMN - line.width) + hint, DIM) if hint else line


def stepper(line: Line, value: str, minus: str, plus: str, key: str) -> Line:
    button(line, "−", minus)
    line.add(f"{value:^6}", BOLD, key).add(" ")
    return button(line, "+", plus)


class Panel:
    def __init__(self):
        self.controls = Controls()
        self.controls.target, self.controls.target_title = herdr.panel_target()
        self.tab = self.load_tab()
        self.dropdown: Optional[str] = None  # the open dropdown's setting name
        self.highlight = 0  # keyboard position inside the open dropdown

    # -- tab memory

    @staticmethod
    def load_tab() -> int:
        try:
            tab = int((paths.STATE_DIR / TAB_FILE).read_text())
        except (OSError, ValueError):
            return 0
        return tab if 0 <= tab < len(TABS) else 0

    def set_tab(self, tab: int) -> None:
        self.tab = tab % len(TABS)
        self.dropdown = None
        try:
            paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
            (paths.STATE_DIR / TAB_FILE).write_text(str(self.tab))
        except OSError:
            pass

    # -- drawing

    def lines(self, config: dict, playback: dict, width: int) -> List[Line]:
        use_icons(config)
        width = max(60, min(width, 96))
        head = Line().add(f"  {ic('speak')} Speak", BOLD).add(f"  {__version__}", DIM)
        auto_on = bool(config.get("auto_read"))
        state = f"{ic('on') if auto_on else ic('off')} {'on' if auto_on else 'off'}"
        head.add(" " * max(1, width - head.width - len(state) - 14)).add("auto-read ", DIM, "a")
        head.add(state, GREEN if auto_on else DIM, "a")
        tabs = Line().add("  ")
        for index, name in enumerate(TABS):
            label = f" {index + 1} {ic(TAB_ICONS[index])} {name} "
            tabs.add(label, REVERSE + BOLD if index == self.tab else DIM, f"tab:{index}").add(" ")
        rule = Line().add("  " + "━" * (width - 4), DIM)
        body = [self.player_tab, self.auto_tab, self.voice_tab, self.shortcuts_tab, self.setup_tab][self.tab](
            config, playback, width)
        footer = Line().add("  ")
        button(footer, f"{ic('close')} Close", "q")
        footer.add(" Tab or 1-5: tabs · letters work everywhere · right-click steps back", DIM)
        return [Line(), head, Line(), tabs, rule, Line()] + body + [Line(), footer, self.controls.status_line()]

    def dropdown_field(self, name: str, label: str, config: dict, hint: str) -> List[Line]:
        """A labelled field showing the current choice; clicking it opens the option list below."""
        options = dropdown_options(name)
        current = str(config.get(name))
        shown = next((text for value, text in options if value == current), current)
        is_open = self.dropdown == name
        line = field(label, f"open:{name}")
        line.add(f" {shown:<{FIELD_WIDTH - 4}} {'▴' if is_open else '▾'} ", REVERSE, f"open:{name}")
        line.add(" " * max(2, HINT_COLUMN - line.width) + hint, DIM)
        lines = [line]
        if is_open:
            pad = " " * (LABEL_WIDTH + 2)
            lines.append(Line().add(pad + "┌" + "─" * (FIELD_WIDTH - 2) + "┐", DIM))
            for index, (value, text) in enumerate(options):
                chosen, lit = value == current, index == self.highlight
                row = Line().add(pad).add("│", DIM)
                row.add(f" {'●' if chosen else ' '} {text:<{FIELD_WIDTH - 6}} ", REVERSE if lit else (GREEN if chosen else ""),
                        f"pick:{name}:{value}")
                lines.append(row.add("│", DIM))
            lines.append(Line().add(pad + "└" + "─" * (FIELD_WIDTH - 2) + "┘", DIM))
        return lines

    def player_tab(self, config: dict, playback: dict, width: int) -> List[Line]:
        lines = [heading("Now playing", width)]
        lines += player_lines(playback, width, ready=self.controls.target_title)
        lines += [transport(playback.get("state", "idle"), ready=bool(self.controls.target)), Line(),
                  heading("Quick settings", width)]
        voice = field("Voice", "tab:2").add(settings.voice_label(config), BOLD, "tab:2").add("   ")
        button(voice, f"{ic('settings')} Change", "tab:2")
        button(voice, f"{ic('play')} Test", "t")
        speed = stepper(field("Speed"), f"{float(config.get('speed') or 1.0):.1f}x", "speed:-", "speed:+", "s")
        auto_on = bool(config.get("auto_read"))
        auto = field("Auto-read", "a").add(f"{ic('on')} on" if auto_on else f"{ic('off')} off",
                                           GREEN if auto_on else DIM, "a")
        follow_on = bool(config.get("mini_follow"))
        mini = field("Mini player").add("  ")
        button(mini, f"{ic('play')} Open or bring here", "open-mini").add(" ")
        mini.add(f"{ic('on') if follow_on else ic('off')} follows you between tabs", GREEN if follow_on else DIM, "p")
        mini.add(" " * max(2, HINT_COLUMN - mini.width) + "p", DIM)
        return lines + [voice, speed, auto, mini]

    def auto_tab(self, config: dict, playback: dict, width: int) -> List[Line]:
        lines = [heading("Auto-read", width),
                 checkbox("Read each response when its agent finishes", bool(config.get("auto_read")), "a", "a"), Line()]
        lines += self.dropdown_field("auto_panes", "Read from", config, "f")
        lines += [Line(), heading("Announcements", width),
                  checkbox('Say the agent and workspace first, like "Claude in api"', bool(config.get("announce")), "m", "m"),
                  checkbox("Say when an agent waits for your input", bool(config.get("announce_blocked")), "b", "b"),
                  Line(), Line().add("  Responses that finish together play in turn; Stop clears the queue.", DIM)]
        return lines

    def voice_tab(self, config: dict, playback: dict, width: int) -> List[Line]:
        lines = [heading("Language", width)]
        lines += self.dropdown_field("language", "Language", config, "l")
        lines += [Line(), heading("Voice", width)]
        engine, current = settings.resolved_engine(config), settings.resolved_voice(config)
        installed = runtime.installed_voices()
        if settings.kokoro_ready(config):
            voices = [("kokoro", name, catalog.voice_description(name) + ("" if name in installed else f" {ic('download')}"))
                      for name in catalog.kokoro_voices_for(config["language"])]
            lines.append(Line().add("  Kokoro  natural, runs on this Mac", DIM))
            lines += self.voice_grid(voices, engine, current, width)
        else:
            lines.append(Line().add("  Install the Kokoro voice on the Setup tab for natural voices.", DIM))
        say = catalog.say_voices_for(config["language"])
        if say:
            lines.append(Line().add("  macOS", DIM))
            lines += self.voice_grid([("say", name, name) for name in say], engine, current, width)
        test = Line().add("  ")
        button(test, f"{ic('play')} Test voice", "t").add(f" t      {ic('download')} downloads on first use (0.5 MB)", DIM)
        lines += [Line(), test, Line(), heading("Speed and quality", width)]
        speed = stepper(field("Speed"), f"{float(config.get('speed') or 1.0):.1f}x", "speed:-", "speed:+", "s")
        lines.append(speed.add(" " * max(2, HINT_COLUMN - speed.width) + "s", DIM))
        lines += self.dropdown_field("model", "Model", config, "o")
        return lines

    @staticmethod
    def voice_grid(voices: List[Tuple[str, str, str]], engine: str, current: str, width: int) -> List[Line]:
        """Voices in aligned columns; the selected one is highlighted and each is clickable."""
        cell = 24
        columns = max(1, min(3, (width - 6) // cell))
        lines = []
        for start in range(0, len(voices), columns):
            line = Line().add("    ")
            for kind, name, label in voices[start:start + columns]:
                chosen = kind == engine and name == current
                text = f"{'●' if chosen else '○'} {label}"[: cell - 1]
                line.add(f"{text:<{cell - 1}}", GREEN + BOLD if chosen else "", f"voice:{kind}:{name}").add(" ")
            lines.append(line)
        return lines

    def shortcuts_tab(self, config: dict, playback: dict, width: int) -> List[Line]:
        prefix, bound = shortcuts.bindings()
        lines = [heading("Herdr keys", width),
                 Line().add(f"  The prefix is {prefix}. Bind keys in ~/.config/herdr/config.toml (see the README).", DIM)]
        for action, description in shortcuts.ACTIONS:
            key = bound.get(action)
            shown = shortcuts.describe_key(key) if key else "not bound"
            lines.append(Line().add(f"    {shown:<18}", CYAN if key else DIM).add(description))
        lines += [Line(), heading("In this panel", width)]
        lines += [Line().add(f"    {key:<18}", CYAN).add(description) for key, description in PANEL_KEYS]
        return lines

    def setup_tab(self, config: dict, playback: dict, width: int) -> List[Line]:
        lines = [heading("Kokoro voice", width), self.runtime_line(config)]
        if settings.kokoro_ready(config) or runtime.runtime_ready():
            repair = Line().add("  ")
            button(repair, f"{ic('setup')} Repair / update", "i").add(" re-checks every file and fetches what's missing", DIM)
            lines.append(repair)
        voices = sorted(runtime.installed_voices())
        model = runtime.model_path(config)
        lines += [Line(), heading("Installed", width),
                  field("Voices").add(", ".join(voices) or "none", "" if voices else DIM),
                  field("Model").add(model.name if model.exists() else "not downloaded"),
                  field("Player").add("running" if client.player_running() else "stopped (starts when needed)"),
                  Line(), heading("Herdr keys", width), self.keys_line(),
                  Line(), heading("macOS", width),
                  checkbox("Media keys and Control Center control Speak while it plays", bool(config.get("media_keys", True)),
                           "k", "k"),
                  Line(), heading("Appearance", width)]
        lines += self.dropdown_field("icons", "Icons", config, "")
        lines += [Line(), heading("Files", width),
                  field("Voice data").add(str(paths.DATA_DIR)),
                  field("Settings").add(str(paths.CONFIG_FILE)),
                  field("Log").add(str(paths.LOG_FILE))]
        return lines

    def keys_line(self) -> Line:
        from .bindings import managed

        line = field("Key bindings")
        if managed():
            line.add("added by Speak  ", GREEN)
            return button(line, "Remove", "unbind-keys")
        line.add("not added by Speak  ", DIM)
        return button(line, "Add free keys", "bind-keys")

    def runtime_line(self, config: dict) -> Line:
        setup = runtime.setup_status()
        if setup.get("state") == "running":
            fraction = setup.get("fraction")
            percent = f" {int(fraction * 100)}%" if fraction is not None else ""
            return field("Status").add(f"Installing: {setup.get('step', '')}{percent}", YELLOW)
        if settings.kokoro_ready(config):
            model = "small model" if config.get("model") == "small" else "full model"
            return field("Status").add(f"{ic('ok')} Ready", GREEN).add(f"  {model}", DIM)
        line = field("Status")
        if setup.get("state") == "failed":
            line.add(f"Setup failed: {str(setup.get('error'))[:50]}  ", RED)
        else:
            line.add("Not installed; using macOS voices  ", YELLOW)
        return button(line, f"{ic('download')} Install (about 650 MB)", "i")

    # -- input

    def handle(self, key: str, backwards: bool = False) -> bool:
        """Apply one key or click; False closes the panel."""
        if self.dropdown and self.dropdown_key(key):
            return True
        if key in ("q", "escape"):
            return False
        if key.startswith("tab:"):
            self.set_tab(int(key[4:]))
            return True
        if key in ("tab", "backtab"):
            self.set_tab(self.tab + (-1 if key == "backtab" or backwards else 1))
            return True
        if len(key) == 1 and key in "12345":
            self.set_tab(int(key) - 1)
            return True
        if key.startswith("open:"):
            name = key[5:]
            self.dropdown = None if self.dropdown == name else name
            current = str(settings.load().get(name))
            self.highlight = next((i for i, (value, _) in enumerate(dropdown_options(name)) if value == current), 0)
            return True
        if self.controls.playback_key(key):
            return True
        self.controls.message = ""
        config = settings.load()
        if key == "t":
            sample = catalog.language(config["language"])["sample"].format(voice=settings.voice_label(config))
            self.controls.in_background("Preparing a sample", lambda: client.speak(sample, "Voice test", config))
            return True
        if key in ("bind-keys", "unbind-keys"):
            from . import bindings

            try:
                if key == "bind-keys":
                    result = bindings.bind()
                    added = ", ".join(shortcuts.describe_key(k) for k in result["added"])
                    self.controls.note(f"Added: {added}" if result["changed"] else
                                       "; ".join(result["notes"]) or "Your keys are already set up")
                else:
                    bindings.unbind()
                    self.controls.note("Removed Speak's key bindings")
            except OSError as error:
                self.controls.note(str(error), YELLOW)
            return True
        if key == "open-mini":
            from .mini import toggle

            try:
                toggle()
            except RuntimeError as error:
                self.controls.note(str(error), YELLOW)
            return True
        if key == "i":
            runtime.start_background_setup([settings.resolved_voice(config, "kokoro")])
            self.controls.note("Installing in the background; you can close this panel.")
            return True
        if not self.apply(config, key, -1 if backwards else 1):
            return True
        self.dropdown = None
        settings.save(config)
        status.refresh(config)
        if key in ("l", "v") or key.startswith(("pick:language:", "voice:")):
            self.ensure_voice(config)
        if (key == "o" or key.startswith("pick:model:")) and runtime.runtime_ready() \
                and not runtime.model_path(config).exists():
            runtime.start_background_setup()
        return True

    def dropdown_key(self, key: str) -> bool:
        """Keyboard inside an open dropdown; False lets other keys through."""
        options = dropdown_options(self.dropdown or "")
        if key == "escape":
            self.dropdown = None
        elif key in ("up", "down"):
            self.highlight = (self.highlight + (1 if key == "down" else -1)) % len(options)
        elif key in ("enter", "space"):
            return self.handle(f"pick:{self.dropdown}:{options[self.highlight][0]}")
        else:
            return False
        return True

    @staticmethod
    def apply(config: dict, key: str, step: int) -> bool:
        """Change config for a settings key or click; False when it changes nothing."""
        if key == "a":
            config["auto_read"] = not config.get("auto_read")
        elif key == "p":
            config["mini_follow"] = not config.get("mini_follow")
        elif key == "k":
            config["media_keys"] = not config.get("media_keys", True)
        elif key == "f":
            config["auto_panes"] = cycle(settings.AUTO_PANES, config.get("auto_panes"), step)
        elif key == "m":
            config["announce"] = not config.get("announce")
        elif key == "b":
            config["announce_blocked"] = not config.get("announce_blocked")
        elif key == "l":
            config["language"] = cycle(list(catalog.LANGUAGES), config["language"], step)
            config["kokoro_voice"] = config["say_voice"] = None  # the new language's defaults
        elif key == "v":
            engine, voice = cycle(voice_choices(config), (settings.resolved_engine(config),
                                                           settings.resolved_voice(config)), step)
            config["engine"] = engine
            config["kokoro_voice" if engine == "kokoro" else "say_voice"] = voice
        elif key.startswith("voice:"):
            _, engine, voice = key.split(":", 2)
            config["engine"] = engine
            config["kokoro_voice" if engine == "kokoro" else "say_voice"] = voice
        elif key in ("s", "speed:+", "speed:-"):
            speeds, current = settings.SPEEDS, float(config.get("speed") or 1.0)
            if key == "s":
                config["speed"] = cycle(speeds, current, step)
            else:  # the buttons stop at the ends
                index = speeds.index(current) if current in speeds else speeds.index(1.0)
                config["speed"] = speeds[max(0, min(len(speeds) - 1, index + (1 if key == "speed:+" else -1)))]
        elif key == "o":
            config["model"] = "small" if config.get("model") != "small" else "full"
        elif key.startswith("pick:"):
            _, name, value = key.split(":", 2)
            if value not in [option for option, _ in dropdown_options(name)]:
                return False
            if name == "language" and value != config.get("language"):
                config["kokoro_voice"] = config["say_voice"] = None
            config[name] = value
        else:
            return False
        return True

    def ensure_voice(self, config: dict) -> None:
        """Download the selected Kokoro voice if needed (about 0.5 MB)."""
        if not runtime.runtime_ready():
            return
        voice = settings.resolved_voice(config, "kokoro")
        if not runtime.voice_path(voice).exists():
            self.controls.in_background(f"Downloading voice {voice}", lambda: runtime.install_voice(voice))


def run(screen_factory=Screen) -> int:
    # Listing macOS voices takes about half a second; do it before the Voice tab needs it.
    threading.Thread(target=catalog.say_voices_for, args=("en-us",), daemon=True).start()
    threading.Thread(target=client.warm, args=(settings.load(),), daemon=True).start()  # speak promptly from here
    panel = Panel()
    with screen_factory() as screen:
        while True:
            width, _ = screen.size()
            screen.draw(panel.lines(settings.load(), client.playback(), width))
            for event in screen.events(0.5):
                if not panel.handle(event.key, event.backwards):
                    return 0

