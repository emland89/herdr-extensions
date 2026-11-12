"""Entry points for Herdr actions, the event hook, the panel, and setup."""

from __future__ import annotations

import argparse
import os
import sys
import traceback

from . import autoread, catalog, client, herdr, paths, runtime, status
from . import config as settings
from .text import clean_for_speech
from .transcripts import last_response

SEEK_SECONDS = 5


def read(mode: str) -> int:
    """read-last / read-selection; pressing again while speaking stops instead."""
    if client.stop():
        return 0
    config = settings.load()
    language = config["language"]
    if mode == "selection":
        raw, title = herdr.selected_text(), "Selection"
    else:
        pane = herdr.target_pane()
        agent = herdr.agent_info(pane)
        raw, title = last_response(agent), herdr.pane_title(pane, agent, language)
    text = clean_for_speech(raw or "", language)
    if not text:
        herdr.notify("Nothing selected" if mode == "selection" else "No response to read yet")
        return 1
    client.speak(text, title, config)
    return 0


def toggle_auto() -> int:
    config = settings.load()
    config["auto_read"] = not config.get("auto_read")
    settings.save(config)
    status.refresh(config)
    herdr.notify("Auto-read on" if config["auto_read"] else "Auto-read off")
    return 0


def control(command: str, **arguments) -> int:
    if not client.control(command, **arguments):
        herdr.notify("Nothing is playing")
    return 0


def setup(arguments: argparse.Namespace) -> int:
    try:
        config = settings.load()
        if arguments.model:
            config["model"] = arguments.model
        ok = runtime.setup(config, voices=arguments.voice or None, echo=True)
    except Exception as error:  # reported below; setup's own failures are already recorded
        print(f"Setup failed: {error}", file=sys.stderr)
        ok = False
    # A build step must never fail the plugin install: speech falls back to `say`,
    # and setup can be retried from the panel.
    return 0 if ok or arguments.build else 1


def keybindings() -> int:
    plugin = paths.PLUGIN_ID
    print(f"""# Speak ({plugin}) key bindings for ~/.config/herdr/config.toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "{plugin}.read-last"
description = "Speak: read last response (again to stop)"

[[keys.command]]
key = "prefix+a"
type = "plugin_action"
command = "{plugin}.read-selection"
description = "Speak: read selection (again to stop)"

[[keys.command]]
key = "prefix+shift+a"
type = "plugin_action"
command = "{plugin}.panel"
description = "Speak: player and settings"

[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "{plugin}.mini-player"
description = "Speak: mini player"

[[keys.command]]
key = "prefix+space"
type = "plugin_action"
command = "{plugin}.toggle-pause"
description = "Speak: pause / resume"

[[keys.command]]
key = "prefix+comma"
type = "plugin_action"
command = "{plugin}.back"
description = "Speak: back 5 seconds"

[[keys.command]]
key = "prefix+period"
type = "plugin_action"
command = "{plugin}.forward"
description = "Speak: forward 5 seconds"

# Optional: playing status and auto-read indicator at the right of the tab bar.
# Add this entry to [ui] tab_bar_right (create the list if you have none):
#   {{ type = "command", command = "cat '{paths.STATUSLINE_FILE}' 2>/dev/null", interval_seconds = 1, timeout_seconds = 1 }}""")
    return 0


def doctor() -> int:
    config = settings.load()
    checks = [
        ("Plugin", f"{paths.PLUGIN_ID} at {paths.PLUGIN_ROOT}"),
        ("Python (plugin)", sys.version.split()[0]),
        ("Runtime", "ready" if runtime.runtime_ready() else "not installed"),
        ("Model", f"{runtime.model_path(config)} {'present' if runtime.model_path(config).exists() else 'missing'}"),
        ("Voices", ", ".join(sorted(runtime.installed_voices())) or "none"),
        ("Engine", f"{settings.resolved_engine(config)} ({settings.voice_label(config)})"),
        ("Language", catalog.language(config['language'])["name"]),
        ("Player", "running" if client.player_running() else "stopped"),
        ("Setup", runtime.setup_status().get("state")),
        ("Data", str(paths.DATA_DIR)),
        ("State", str(paths.STATE_DIR)),
    ]
    for name, value in checks:
        print(f"{name:<16} {value}")
    return 0


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="speak.py", description="Speak: hear your coding agents in Herdr.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("last", "selection", "stop", "toggle-pause", "forward", "back", "skip", "toggle-auto", "event",
                 "panel", "open-panel", "mini", "mini-player", "follow", "keybindings", "doctor", "statusline"):
        sub.add_parser(name)
    setup_parser = sub.add_parser("setup", help="install the Kokoro voice runtime, model, and voices")
    setup_parser.add_argument("--voice", action="append", help="also install this Kokoro voice (repeatable)")
    setup_parser.add_argument("--model", choices=sorted(catalog.KOKORO_MODELS))
    setup_parser.add_argument("--build", action="store_true", help="running as Herdr's build step: never fail")
    arguments = parser.parse_args(argv[1:])
    command = arguments.command
    try:
        if command in ("last", "selection"):
            return read(command)
        if command == "stop":
            client.stop()
            return 0
        if command == "toggle-pause":
            return control("toggle-pause")
        if command == "forward":
            return control("seek", seconds=SEEK_SECONDS)
        if command == "back":
            return control("seek", seconds=-SEEK_SECONDS)
        if command == "skip":
            return control("skip")
        if command == "toggle-auto":
            return toggle_auto()
        if command == "event":
            autoread.handle_event(settings.load(), os.environ.get("HERDR_PLUGIN_EVENT_JSON", ""))
            return 0
        if command == "panel":
            from .panel import run

            return run()
        if command == "open-panel":
            herdr.open_panel()
            return 0
        if command == "mini":
            from .mini import run as run_mini

            return run_mini()
        if command == "mini-player":
            from .mini import toggle

            toggle()
            return 0
        if command == "follow":
            from .mini import follow

            follow(settings.load())
            return 0
        if command == "setup":
            return setup(arguments)
        if command == "keybindings":
            return keybindings()
        if command == "doctor":
            return doctor()
        if command == "statusline":
            print(status.refresh(settings.load()))
            return 0
    except Exception as error:  # surface every failure in Herdr and the log, never silently
        if command not in ("event", "follow"):  # events fire constantly; log them without notifying
            herdr.notify(str(error))
        paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(paths.LOG_FILE, "a") as log:
            log.write(f"{command}: {error!r}\n{traceback.format_exc()}\n")
        if sys.stderr.isatty():
            print(f"speak: {error}", file=sys.stderr)
        return 1
    return 2
