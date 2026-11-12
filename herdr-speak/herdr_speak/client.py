"""Talk to the player, starting it on demand.

Without the runtime (before setup, or if it failed), speech falls back to the
`say` command directly: pause and stop still work, seeking and skipping don't.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import stat
import subprocess
import time
from contextlib import contextmanager
from typing import Optional

from . import config as settings
from . import paths, runtime, status
from .text import defuse_say


class PlayerUnavailable(RuntimeError):
    pass


def _own_socket(path) -> bool:
    """Only talk to a socket this user created: anything else isn't our player."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()


def request(payload: dict, timeout: float = 5.0) -> dict:
    path = paths.socket_path()
    if not _own_socket(path):
        raise PlayerUnavailable("player is not running")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        try:
            connection.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as error:
            raise PlayerUnavailable("player is not running") from error
        connection.sendall(json.dumps(payload).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
    response = json.loads(data or b"{}")
    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "player error")
    return response


def player_running() -> bool:
    try:
        request({"command": "status"}, timeout=1.0)
    except (PlayerUnavailable, OSError, RuntimeError, json.JSONDecodeError):
        return False
    return True


def start_player(timeout: float = 15.0) -> bool:
    """Start the player when the runtime is installed; True once it answers."""
    if player_running():
        return True
    if not runtime.runtime_ready():
        # Installed before, but the plugin's requirements changed (an update): rebuild in
        # the background and use macOS speech until it's done.
        if paths.VENV_DIR.exists() and not runtime.setup_running():
            from .herdr import notify

            runtime.start_background_setup()
            notify("Updating Speak's voice runtime; macOS speech until it's ready")
        return False
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.LOG_FILE, "a") as log:
        subprocess.Popen([str(paths.RUNTIME_PYTHON), "-W", "ignore", "-m", "herdr_speak.daemon"],
                         cwd=str(paths.PLUGIN_ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if player_running():
            return True
        time.sleep(0.1)
    return False


def warm(config: dict) -> None:
    """Get the voice loaded before it's needed, without waiting: start the player warming
    up, or ask a running one to. A no-op without the runtime."""
    try:
        speech = settings.speech_settings(settings.sanitize(dict(settings.DEFAULTS, **config)))
        if speech["engine"] != "kokoro" or not runtime.runtime_ready():
            return
    except Exception:  # warming is an optimization; never let it break the caller
        return
    try:
        request({"command": "warm", "speech": speech}, timeout=1.0)
        return
    except (PlayerUnavailable, OSError, RuntimeError, ValueError):
        pass
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HERDR_SPEAK_WARM=json.dumps(speech))
    with open(paths.LOG_FILE, "a") as log:
        subprocess.Popen([str(paths.RUNTIME_PYTHON), "-W", "ignore", "-m", "herdr_speak.daemon"], env=env,
                         cwd=str(paths.PLUGIN_ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)


# ---------------------------------------------------------------- fallback


def _fallback_pid() -> Optional[int]:
    try:
        info = json.loads(paths.FALLBACK_PID.read_text())
        pid = int(info["pid"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return None
    command = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return pid if "say" in command else None  # guard against a recycled PID


@contextmanager
def _fallback_lock():
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.STATE_DIR / "fallback.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _stop_stamp() -> str:
    try:
        return (paths.STATE_DIR / "fallback.stopped").read_text()
    except OSError:
        return ""


def _fallback_start(text: str, title: str, speech: dict) -> None:
    """Start `say` (call with the fallback lock held); the text goes in on stdin."""
    command = ["/usr/bin/say", "-v", speech["voice"], "-r", str(round(185 * speech["speed"])), "-f", "-"]
    with open(paths.LOG_FILE, "a") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                   start_new_session=True)
    paths.FALLBACK_PID.write_text(json.dumps({"pid": process.pid, "title": title, "paused": False}))
    if process.stdin is not None:
        process.stdin.write(defuse_say(text).encode("utf-8"))
        process.stdin.close()


def _fallback_speak(text: str, title: str, speech: dict, queue: bool) -> None:
    if not queue:
        with _fallback_lock():
            _fallback_stop()
            _fallback_start(text, title, speech)
        return
    # Queued (auto-read): wait for the current speech; give up if the user stops speech meanwhile.
    stamp = _stop_stamp()
    deadline = time.time() + 600
    while time.time() < deadline and _stop_stamp() == stamp:
        with _fallback_lock():
            if _fallback_pid() is None:
                _fallback_start(text, title, speech)
                return
        time.sleep(0.5)


def _fallback_stop() -> bool:
    pid = _fallback_pid()
    paths.FALLBACK_PID.unlink(missing_ok=True)
    if pid is None:
        return False
    try:
        os.killpg(pid, signal.SIGCONT)  # a stopped process can't act on SIGTERM
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True


def _fallback_toggle_pause() -> bool:
    pid = _fallback_pid()
    if pid is None:
        return False
    info = json.loads(paths.FALLBACK_PID.read_text())
    info["paused"] = not info.get("paused")
    os.killpg(pid, signal.SIGSTOP if info["paused"] else signal.SIGCONT)
    paths.FALLBACK_PID.write_text(json.dumps(info))
    return True


# ---------------------------------------------------------------- public interface


def playback() -> dict:
    if player_running():
        return status.read_playback()
    pid = _fallback_pid()
    if pid is None:
        return {"state": "idle"}
    info = json.loads(paths.FALLBACK_PID.read_text())
    return {"state": "paused" if info.get("paused") else "playing", "title": info.get("title"), "fallback": True}


def is_busy() -> bool:
    return playback().get("state", "idle") != "idle"


def speak(text: str, title: str, config: dict, queue: bool = False, source: str = "manual") -> None:
    speech = settings.speech_settings(config)
    if start_player():
        request({"command": "speak", "text": text, "title": title, "speech": speech, "queue": queue,
                 "source": source})
        return
    if speech["engine"] == "kokoro":
        speech = dict(speech, engine="say", voice=settings.resolved_voice(config, "say"))
    _fallback_speak(text, title, speech, queue)


def stop() -> bool:
    """Stop speech and drop queued items; False when nothing was playing."""
    stopped = False
    if player_running():
        stopped = request({"command": "status"})["status"]["state"] != "idle"
        request({"command": "stop"})
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (paths.STATE_DIR / "fallback.stopped").write_text(str(time.time()))  # drops queued fallback speech
    return _fallback_stop() or stopped


def control(command: str, **arguments) -> bool:
    """pause, resume, toggle-pause, seek, skip. False when nothing is playing or it isn't supported."""
    if player_running():
        response = request(dict(arguments, command=command))
        return response["status"]["state"] != "idle" or command == "skip"
    if command == "toggle-pause":
        return _fallback_toggle_pause()
    if _fallback_pid() is not None:
        raise RuntimeError("Seeking and skipping need the Kokoro runtime: open the Speak panel and install it")
    return False
