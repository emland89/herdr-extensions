"""Where the plugin keeps its files.

Herdr provides config and state directories to runtime commands. Build commands
don't receive them, so the downloaded runtime and voices live in a fixed data
directory that every command can find.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

HOME = Path.home()
PLUGIN_ID = os.environ.get("HERDR_PLUGIN_ID") or "emilapps.speak"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

STATE_DIR = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or HOME / ".local/state/herdr/plugins" / PLUGIN_ID)
CONFIG_DIR = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR") or HOME / ".config/herdr/plugins/config" / PLUGIN_ID)
CONFIG_FILE = CONFIG_DIR / "config.json"

# Keep this path short: espeak-ng silently ignores data paths longer than about
# 160 characters, and its data ships inside the runtime environment.
DATA_DIR = Path(
    os.environ.get("HERDR_SPEAK_DATA_DIR")
    or Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "herdr-speak"
)
RUNTIME_DIR = DATA_DIR / "runtime"
VENV_DIR = RUNTIME_DIR / "venv"
RUNTIME_PYTHON = VENV_DIR / "bin/python"
RUNTIME_MARKER = RUNTIME_DIR / "installed.json"
BOOTSTRAP_DIR = DATA_DIR / "bootstrap"  # holds uv when it isn't on PATH
KOKORO_DIR = DATA_DIR / "kokoro"
VOICES_DIR = KOKORO_DIR / "voices"
SETUP_STATUS = DATA_DIR / "setup.json"
SETUP_LOG = DATA_DIR / "setup.log"
SETUP_LOCK = DATA_DIR / "setup.lock"

STATUS_FILE = STATE_DIR / "status.json"  # playback state, written by the daemon
STATUSLINE_FILE = STATE_DIR / "statusline"  # one line for Herdr's tab bar
PANES_FILE = STATE_DIR / "panes.json"  # auto-read: last status and spoken text per pane
LOG_FILE = STATE_DIR / "speak.log"
FALLBACK_PID = STATE_DIR / "fallback.json"  # `say` started without the runtime


def private_dir() -> Path:
    """A short directory only this user can use: ~/.cache/herdr-speak, mode 0700.

    For files that need a short path (Unix sockets, espeak data). Never a shared
    temp folder: another local user could create the path first.
    """
    path = HOME / ".cache" / "herdr-speak"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError(f"{path} must be a directory owned by you")
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)
    return path


def socket_path() -> Path:
    path = STATE_DIR / "speakd.sock"
    # Unix socket paths are limited to 104 bytes on macOS.
    if len(str(path)) < 100:
        return path
    return private_dir() / "speakd.sock"
