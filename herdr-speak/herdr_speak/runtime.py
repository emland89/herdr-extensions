"""Install the voice runtime, the Kokoro model, and voices.

Everything goes under paths.DATA_DIR, so removing that folder removes it all:

    runtime/venv   Python 3.12 environment from requirements.lock (hash-checked)
    python/        Python itself, when uv had to download it
    bootstrap/     uv, when it isn't already on PATH
    kokoro/        model, tokenizer, and voices, pinned and checked by sha256

Setup runs from Herdr's build step on `herdr plugin install`, from the panel, or
as `python3 speak.py setup`. It is idempotent and resumes partial downloads.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from . import catalog, paths

PYTHON_VERSION = "3.12"
LOCK_FILE = paths.PLUGIN_ROOT / "requirements.lock"
BOOTSTRAP_LOCK = paths.PLUGIN_ROOT / "bootstrap.lock"  # uv itself, when the system has none or an old one
# Older uv versions trust a compromised certificate authority (GHSA-hq85-5cpj-mr62).
MIN_SYSTEM_UV = (0, 13, 4)
# Earlier installs of the agent-tts plugin keep the same fp32 model; reuse it instead of downloading.
REUSABLE_MODELS = [Path.home() / ".local/share/agent-tts/voices/kokoro/model.onnx"]

Progress = Callable[[str, Optional[float]], None]


# ---------------------------------------------------------------- state


def lock_digest() -> str:
    return hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()


def runtime_ready() -> bool:
    try:
        marker = json.loads(paths.RUNTIME_MARKER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return interpreter_usable() and marker.get("lock_sha256") == lock_digest()


def interpreter_usable() -> bool:
    """The environment's Python exists and lives under DATA_DIR, so removing another
    tool's Python can't break Speak."""
    if not paths.RUNTIME_PYTHON.exists():
        return False
    try:
        paths.RUNTIME_PYTHON.resolve().relative_to(paths.DATA_DIR.resolve())
    except ValueError:
        return False
    return True


def model_path(config: dict) -> Path:
    remote = catalog.KOKORO_MODELS.get(config.get("model") or "full", catalog.KOKORO_MODELS["full"])[0]
    return paths.KOKORO_DIR / Path(remote).name


def tokenizer_path() -> Path:
    return paths.KOKORO_DIR / catalog.KOKORO_TOKENIZER[0]


def voice_path(name: str) -> Path:
    return paths.VOICES_DIR / f"{name}.bin"


def installed_voices() -> set:
    return {path.stem for path in paths.VOICES_DIR.glob("*.bin")} if paths.VOICES_DIR.exists() else set()


def setup_status() -> dict:
    try:
        status = json.loads(paths.SETUP_STATUS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"state": "none"}
    # A crashed setup leaves "running" behind; the lock tells whether one is alive.
    if status.get("state") == "running" and not setup_running():
        status["state"] = "failed"
        status.setdefault("error", "Setup stopped unexpectedly")
    return status


def setup_running() -> bool:
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.SETUP_LOCK, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


# ---------------------------------------------------------------- downloads


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path, size: int, sha256: str, progress: Optional[Progress] = None,
             label: str = "") -> None:
    """Fetch with curl (resumable, uses the system certificate store) and verify sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # One downloader per file: the panel and the player can ask for the same voice at once.
    locks = paths.DATA_DIR / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with open(locks / f"{dest.name}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _download_locked(url, dest, size, sha256, progress, label)


def _download_locked(url: str, dest: Path, size: int, sha256: str, progress: Optional[Progress], label: str) -> None:
    if dest.exists() and dest.stat().st_size == size and sha256_of(dest) == sha256:
        return
    partial = dest.with_name(dest.name + ".part")
    # https only (file: for local tests), including redirects; never more than the expected size.
    command = ["/usr/bin/curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
               "--proto", "=https,file", "--proto-redir", "=https", "--max-filesize", str(size + 1024),
               "--continue-at", "-", "--output", str(partial), url]
    process = subprocess.Popen(command, stderr=subprocess.PIPE, text=True)
    while process.poll() is None:
        if progress and partial.exists():
            progress(label, min(partial.stat().st_size / size, 1.0))
        time.sleep(0.5)
    _, errors = process.communicate()
    if process.returncode not in (0, 33):  # 33: range not satisfiable (already complete)
        raise RuntimeError(f"Download failed: {url}: {(errors or '').strip()}")
    if sha256_of(partial) != sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {dest.name}; the partial download was removed, try again")
    partial.replace(dest)


def install_tokenizer(progress: Optional[Progress] = None) -> None:
    remote, size, sha256 = catalog.KOKORO_TOKENIZER
    download(f"{catalog.KOKORO_BASE_URL}/{remote}", tokenizer_path(), size, sha256, progress, "Tokenizer")


def install_model(variant: str = "full", progress: Optional[Progress] = None) -> None:
    remote, size, sha256 = catalog.KOKORO_MODELS.get(variant, catalog.KOKORO_MODELS["full"])
    dest = paths.KOKORO_DIR / Path(remote).name
    partial = dest.with_name(dest.name + ".part")
    if not dest.exists() and not partial.exists():
        for candidate in REUSABLE_MODELS:
            if candidate.exists() and candidate.stat().st_size == size and sha256_of(candidate) == sha256:
                # Into the partial file: download() verifies it and moves it into place.
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, partial)
                break
    download(f"{catalog.KOKORO_BASE_URL}/{remote}", dest, size, sha256, progress,
             f"Kokoro model ({size // 1_000_000} MB)")


def install_voice(name: str, progress: Optional[Progress] = None) -> None:
    if name not in catalog.KOKORO_VOICES:
        raise ValueError(f"Unknown Kokoro voice: {name}")
    download(f"{catalog.KOKORO_BASE_URL}/voices/{name}.bin", voice_path(name), catalog.VOICE_SIZE,
             catalog.KOKORO_VOICES[name], progress, f"Voice {name}")


# ---------------------------------------------------------------- python runtime


def _run(command: list, env: Optional[dict] = None) -> None:
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.SETUP_LOG, "a") as log:
        log.write(f"$ {' '.join(map(str, command))}\n")
        log.flush()
        result = subprocess.run(command, stdout=log, stderr=log, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"{Path(command[0]).name} failed (exit {result.returncode}); see {paths.SETUP_LOG}")


def find_uv(progress: Optional[Progress] = None) -> str:
    bootstrapped = paths.BOOTSTRAP_DIR / "bin/uv"
    if bootstrapped.exists():
        return str(bootstrapped)
    found = shutil.which("uv")
    if found and uv_version(found) >= MIN_SYSTEM_UV:
        return found
    # uv installs from PyPI with any Python 3.8+, including the macOS system Python; the
    # wheel is checked against the hashes in bootstrap.lock.
    if progress:
        progress("Installing uv", None)
    _run([sys.executable, "-m", "venv", str(paths.BOOTSTRAP_DIR)])
    _run([str(paths.BOOTSTRAP_DIR / "bin/python"), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
          "--require-hashes", "-r", str(BOOTSTRAP_LOCK)])
    return str(bootstrapped)


def uv_version(binary: str) -> tuple:
    """(major, minor, patch) of a uv binary; (0,) when it can't be read."""
    try:
        output = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10).stdout
        return tuple(int(part) for part in output.split()[1].split(".")[:3])
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return (0,)


def uv_environment() -> dict:
    """Keep everything uv downloads inside DATA_DIR, so removing that folder removes it all."""
    return dict(
        os.environ,
        UV_PYTHON_INSTALL_DIR=str(paths.DATA_DIR / "python"),
        UV_CACHE_DIR=str(paths.DATA_DIR / "cache"),
        UV_LINK_MODE="copy",  # the cache is deleted after installing
        UV_PYTHON_PREFERENCE="only-managed",  # never link to an interpreter outside DATA_DIR
    )


def install_runtime(progress: Optional[Progress] = None) -> None:
    if runtime_ready():
        return
    uv = find_uv(progress)
    env = uv_environment()
    paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        marker = json.loads(paths.RUNTIME_MARKER.read_text())
    except (OSError, ValueError):
        marker = {}
    # Rebuild from scratch when the Python version changed or the interpreter disappeared.
    interpreter = paths.RUNTIME_PYTHON
    if paths.VENV_DIR.exists() and (marker.get("python") not in (None, PYTHON_VERSION) or not interpreter_usable()):
        shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
    if progress:
        progress(f"Creating Python {PYTHON_VERSION} environment", None)
    if not interpreter.exists():
        _run([uv, "venv", "--quiet", "--python", PYTHON_VERSION, str(paths.VENV_DIR)], env)
    if progress:
        progress("Installing voice packages (about 260 MB)", None)
    # sync, not install: packages dropped from the lock are removed on upgrade.
    _run([uv, "pip", "sync", "--quiet", "--python", str(interpreter), "--require-hashes", str(LOCK_FILE)], env)
    _run([str(interpreter), "-c", "import onnxruntime, sounddevice, numpy, misaki.en, misaki.espeak"])
    shutil.rmtree(paths.DATA_DIR / "cache", ignore_errors=True)
    paths.RUNTIME_MARKER.write_text(json.dumps({"lock_sha256": lock_digest(), "python": PYTHON_VERSION,
                                                "installed_at": int(time.time())}))


# ---------------------------------------------------------------- orchestration


class StatusWriter:
    def __init__(self, echo: bool):
        self.echo = echo
        self.last_echo = ""

    def write(self, **status) -> None:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        status["updated"] = time.time()
        temporary = paths.SETUP_STATUS.with_suffix(".tmp")
        temporary.write_text(json.dumps(status))
        temporary.replace(paths.SETUP_STATUS)

    def progress(self, step: str, fraction: Optional[float]) -> None:
        self.write(state="running", step=step, fraction=fraction)
        line = step + (f" {int(fraction * 100)}%" if fraction is not None else "")
        if self.echo and (fraction is None or line != self.last_echo and int(fraction * 100) % 10 == 0):
            print(line, flush=True)
            self.last_echo = line


def setup(config: dict, voices: Optional[list] = None, echo: bool = False) -> bool:
    """Install everything the configured Kokoro voice needs. Returns success."""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    writer = StatusWriter(echo)
    with open(paths.SETUP_LOCK, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if echo:
                print("Setup is already running.")
            return False
        try:
            install_runtime(writer.progress)
            install_tokenizer(writer.progress)
            install_model(config.get("model") or "full", writer.progress)
            from .config import resolved_voice  # local import: config imports this module lazily

            # The configured voice, plus any extra ones asked for.
            for name in dict.fromkeys([resolved_voice(config, "kokoro"), *(voices or [])]):
                install_voice(name, writer.progress)
        except Exception as error:  # report every failure to the panel and the build log
            writer.write(state="failed", error=str(error))
            if echo:
                print(f"Setup failed: {error}", file=sys.stderr)
            return False
        writer.write(state="done", step="Kokoro voice installed")
        if echo:
            print("Kokoro voice installed.")
        return True


def start_background_setup(voices: Optional[list] = None) -> None:
    """Run setup detached, so the panel can show progress and stay responsive."""
    if setup_running():
        return
    command = [sys.executable, str(paths.PLUGIN_ROOT / "speak.py"), "setup"]
    for voice in voices or []:
        command += ["--voice", voice]
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.SETUP_LOG, "a") as log:
        subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         cwd=str(paths.PLUGIN_ROOT), start_new_session=True)
