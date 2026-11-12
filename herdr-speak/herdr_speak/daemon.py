"""The speech player: synthesizes queued text and plays it with pause and seek.

Runs in the runtime environment (numpy, sounddevice, onnxruntime, misaki):

    runtime/venv/bin/python -m herdr_speak.daemon

The plugin's commands start it on demand and talk to it over a Unix socket, one
JSON request per connection. It keeps the voice loaded between responses and
exits after `keep_alive_minutes` without playback.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Callable, Dict, List, Optional

import numpy as np

from . import catalog, paths, status
from . import config as settings
from .text import defuse_say, paragraphs, plain_label

SAMPLE_RATE = catalog.SAMPLE_RATE
MAX_PHONEMES = 510  # Kokoro's context, minus the two padding tokens
PARAGRAPH_PAUSE = np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.float32)
CHARS_PER_SECOND = 14.0  # typical speech at speed 1.0, until the first paragraph gives the real rate
LOOKAHEAD = 2  # items synthesized ahead of playback


def log(message: str) -> None:
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.LOG_FILE, "a") as handle:
        handle.write(f"{time.strftime('%H:%M:%S')} speakd: {message}\n")


# ---------------------------------------------------------------- engines


class KokoroEngine:
    """Kokoro's reference pipeline: Misaki phonemes in, style vector chosen by length."""

    def __init__(self, model_variant: str):
        import onnxruntime

        from . import runtime

        self._prepare_espeak()
        self.vocab = json.loads(runtime.tokenizer_path().read_text())["model"]["vocab"]
        model = runtime.model_path({"model": model_variant})
        self.session = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        self.g2p: Dict[str, Callable] = {}
        self.voices: Dict[str, np.ndarray] = {}

    @staticmethod
    def _prepare_espeak() -> None:
        # espeak-ng ignores data paths longer than about 160 characters.
        import espeakng_loader
        from misaki import espeak  # noqa: F401  (sets the bundled library and data path)
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        data = espeakng_loader.get_data_path()
        if len(data) > 150:
            from importlib.metadata import version

            # Versioned, so an upgrade gets fresh data; in the user's private directory, never /tmp.
            private = str(paths.private_dir())
            short = os.path.join(private, f"espeak-{version('espeakng-loader')}")
            if not os.path.isdir(short):
                staging = tempfile.mkdtemp(dir=private)
                shutil.copytree(data, os.path.join(staging, "data"))
                os.replace(os.path.join(staging, "data"), short)
                os.rmdir(staging)
            EspeakWrapper.set_data_path(short)

    def _g2p(self, language: str) -> Callable:
        if language not in self.g2p:
            from misaki import espeak

            info = catalog.language(language)
            if info["espeak"] is None:
                from misaki import en

                british = info["kokoro"] == "b"
                self.g2p[language] = en.G2P(trf=False, british=british, fallback=espeak.EspeakFallback(british=british))
            else:
                self.g2p[language] = espeak.EspeakG2P(language=info["espeak"])
        return self.g2p[language]

    def _voice(self, name: str) -> np.ndarray:
        if name not in self.voices:
            from . import runtime

            path = runtime.voice_path(name)
            if not path.exists():
                runtime.install_voice(name)
            # One 256-wide style vector per input length.
            self.voices[name] = np.fromfile(path, dtype=np.float32).reshape(-1, 256)
        return self.voices[name]

    def phoneme_chunks(self, text: str, language: str) -> List[str]:
        phonemes, _ = self._g2p(language)(text)
        chunks = []
        while len(phonemes) > MAX_PHONEMES:
            cut = phonemes.rfind(" ", 0, MAX_PHONEMES) + 1 or MAX_PHONEMES
            chunks.append(phonemes[:cut].strip())
            phonemes = phonemes[cut:]
        return chunks + [phonemes.strip()]

    def synthesize(self, text: str, language: str, voice: str, speed: float) -> np.ndarray:
        style = self._voice(voice)
        audio = []
        for phonemes in self.phoneme_chunks(text, language):
            tokens = [self.vocab[p] for p in phonemes if p in self.vocab]
            if not tokens:
                continue
            output = self.session.run(None, {
                "input_ids": np.array([[0, *tokens, 0]], dtype=np.int64),
                "style": style[min(len(tokens), len(style) - 1)][None, :],
                "speed": np.array([speed], dtype=np.float32),
            })[0]
            audio.append(np.asarray(output, dtype=np.float32).reshape(-1))
        return np.concatenate(audio) if audio else np.zeros(0, dtype=np.float32)


class SayEngine:
    """macOS speech, rendered to 24 kHz audio so it plays through the same player."""

    def synthesize(self, text: str, language: str, voice: str, speed: float) -> np.ndarray:
        with tempfile.TemporaryDirectory(prefix="herdr-speak-") as directory:
            source, target = os.path.join(directory, "in.txt"), os.path.join(directory, "out.wav")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write(defuse_say(text))  # no embedded [[...]] commands from transcripts
            command = ["/usr/bin/say", "-f", source, "-o", target, "--file-format=WAVE",
                       f"--data-format=LEI16@{SAMPLE_RATE}", "-r", str(round(185 * speed))]
            if voice:
                command[1:1] = ["-v", voice]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"say failed for voice {voice}: {result.stderr.strip()}")
            with wave.open(target) as audio:
                frames = audio.readframes(audio.getnframes())
        return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


# ---------------------------------------------------------------- playback


class Item:
    def __init__(self, title: str, texts: List[str], speech: dict, source: str):
        self.title = plain_label(title)
        self.texts = texts
        self.speech = speech
        self.source = source
        self.chunks: List[np.ndarray] = []  # appended, never copied: the audio callback reads across them
        self.length = 0  # samples in all chunks
        self.synthesized = 0  # paragraphs done
        self.done = not texts  # all paragraphs synthesized (or failed)
        self.error: Optional[str] = None
        self.total_chars = sum(len(text) for text in texts)
        self.chars_done = 0
        self.speed = float(speech.get("speed") or 1.0)

    def estimated_samples(self) -> int:
        """The whole item's length: exact once synthesized, else extrapolated from the audio so far.

        Using only the synthesized length would make the total grow paragraph by paragraph,
        so the progress bar would slide backwards while it plays.
        """
        if self.done:
            return self.length
        rate = self.length / self.chars_done if self.chars_done else SAMPLE_RATE / (CHARS_PER_SECOND * self.speed)
        return max(self.length, int(self.length + (self.total_chars - self.chars_done) * rate))

    def append(self, audio: np.ndarray) -> None:
        self.chunks.append(audio)
        self.length += len(audio)

    def read_into(self, out: np.ndarray, position: int) -> int:
        """Copy samples from `position` into out; returns how many were available."""
        written, offset = 0, 0
        for chunk in self.chunks:
            end = offset + len(chunk)
            if end > position + written and written < len(out):
                start = position + written - offset
                count = min(len(chunk) - start, len(out) - written)
                out[written:written + count] = chunk[start:start + count]
                written += count
            offset = end
            if written >= len(out):
                break
        return written


class Speaker:
    """Queue, synthesis thread, and the audio callback's view of playback."""

    def __init__(self, engines: Optional[Dict[str, object]] = None):
        self.lock = threading.RLock()
        self.items: List[Item] = []  # items[0] is playing
        self.position = 0  # samples into items[0]
        self.paused = False
        self.paused_at = 0.0
        self.engines: Dict[str, object] = engines if engines is not None else {}
        self.wake = threading.Event()
        self.last_activity = time.time()
        self.errors: List[str] = []
        threading.Thread(target=self._synthesis_loop, daemon=True).start()

    # -- commands

    def speak(self, text: str, title: str, speech: dict, queue: bool, source: str = "manual") -> None:
        item = Item(title, paragraphs(text), speech, source)
        with self.lock:
            if not queue:
                self.items.clear()
                self.position = 0
                self.paused = False
            self.items.append(item)
            self.last_activity = time.time()
        self.wake.set()

    def stop(self) -> None:
        with self.lock:
            self.items.clear()
            self.position = 0
            self.paused = False

    def set_paused(self, paused: Optional[bool] = None) -> None:
        with self.lock:
            if self.items:
                was = self.paused
                self.paused = (not self.paused) if paused is None else paused
                if self.paused and not was:
                    self.paused_at = time.time()
            self.last_activity = time.time()

    def seek(self, seconds: float) -> None:
        with self.lock:
            if self.items:
                limit = self.items[0].length
                self.position = int(min(max(self.position + seconds * SAMPLE_RATE, 0), limit))

    def skip(self) -> None:
        with self.lock:
            if self.items:
                self.items.pop(0)
                self.position = 0
                self.paused = False

    def snapshot(self) -> dict:
        with self.lock:
            if not self.items:
                return {"state": "idle"}
            item = self.items[0]
            buffering = self.position >= item.length and not item.done
            return {
                "state": "paused" if self.paused else ("buffering" if buffering else "playing"),
                "title": item.title,
                "source": item.source,
                "position": self.position / SAMPLE_RATE,
                "duration": item.estimated_samples() / SAMPLE_RATE,
                "synthesized": item.length / SAMPLE_RATE,
                "complete": item.done,
                "queued": len(self.items) - 1,
                "voice": item.speech.get("voice"),
                "paused_seconds": time.time() - self.paused_at if self.paused else 0.0,
            }

    def busy(self) -> bool:
        with self.lock:
            return bool(self.items)

    # -- synthesis

    def warm(self, speech: dict) -> None:
        """Load everything the first sentence needs: engine, phonemizer, and voice."""
        try:
            engine = self.engine(speech)
            if isinstance(engine, KokoroEngine):
                engine.phoneme_chunks("Ready.", speech.get("language") or catalog.DEFAULT_LANGUAGE)
                engine._voice(speech.get("voice") or catalog.default_kokoro_voice(speech.get("language")))
        except Exception as error:  # warming is best effort; the first speak reports real errors
            log(f"warm-up failed: {error!r}")

    def engine(self, speech: dict):
        key = "kokoro:" + speech.get("model", "full") if speech.get("engine") == "kokoro" else "say"
        if key not in self.engines:
            self.engines[key] = KokoroEngine(speech.get("model", "full")) if key.startswith("kokoro") else SayEngine()
        return self.engines[key]

    def _next_job(self) -> Optional[Item]:
        with self.lock:
            return next((item for item in self.items[:LOOKAHEAD] if not item.done), None)

    def _synthesis_loop(self) -> None:
        while True:
            item = self._next_job()
            if item is None:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            speech = item.speech
            try:
                audio = self.engine(speech).synthesize(item.texts[item.synthesized], speech.get("language"),
                                                       speech.get("voice"), float(speech.get("speed") or 1.0))
            except Exception as error:  # keep the player alive; report and drop this item
                item.error = str(error)
                log(f"synthesis failed: {error!r}")
                with self.lock:
                    item.done = True
                    self.errors.append(item.error)
                continue
            with self.lock:
                item.append(np.concatenate([audio, PARAGRAPH_PAUSE]))
                item.chars_done += len(item.texts[item.synthesized])
                item.synthesized += 1
                item.done = item.synthesized >= len(item.texts)

    # -- audio callback

    def fill(self, out: np.ndarray) -> None:
        """Write the next len(out) samples; silence while paused, idle, or buffering."""
        out[:] = 0
        with self.lock:
            written = 0
            while written < len(out) and self.items and not self.paused:
                item = self.items[0]
                count = item.read_into(out[written:], self.position)
                if count == 0:
                    if not item.done:
                        break  # still synthesizing
                    self.items.pop(0)
                    self.position = 0
                    continue
                self.position += count
                written += count
            if self.items:
                self.last_activity = time.time()


class SoundDeviceOutput:
    """Plays from Speaker.fill; the stream is open only while there is something to play."""

    def __init__(self, fill: Callable[[np.ndarray], None]):
        self.fill = fill
        self.stream = None

    def _callback(self, outdata, frames, time_info, flags) -> None:  # noqa: ARG002
        self.fill(outdata[:, 0])

    def start(self) -> None:
        if self.stream is None:
            import sounddevice

            self.stream = sounddevice.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                                   callback=self._callback)
            self.stream.start()

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None


class NullOutput:
    """Consumes audio without a sound device, `speedup` times faster than real time. For tests."""

    def __init__(self, fill: Callable[[np.ndarray], None], speedup: float = 1.0):
        self.fill = fill
        self.speedup = speedup
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True

        def run() -> None:
            block = np.zeros(1200, dtype=np.float32)
            while self.running:
                self.fill(block)
                time.sleep(len(block) / SAMPLE_RATE / self.speedup)

        threading.Thread(target=run, daemon=True).start()

    def stop(self) -> None:
        self.running = False


# ---------------------------------------------------------------- server


class Daemon:
    def __init__(self, speaker: Speaker, output, keep_alive: Optional[float] = None, media=None):
        self.speaker = speaker
        self.output = output
        self.keep_alive = keep_alive
        self.running = True
        self.media = media  # MediaControls, or None (tests, or media keys unavailable)
        self.reported_errors = 0
        # Opening and closing the stream happen on request threads and the tick loop.
        self.output_lock = threading.Lock()

    def handle(self, request: dict) -> dict:
        command = request.get("command")
        speaker = self.speaker
        if command == "speak":
            speaker.speak(request["text"], request.get("title") or "Speak", request["speech"],
                          bool(request.get("queue")), request.get("source") or "manual")
            with self.output_lock:
                self.output.start()
        elif command == "stop":
            speaker.stop()
        elif command == "pause":
            speaker.set_paused(True)
        elif command == "resume":
            speaker.set_paused(False)
        elif command == "toggle-pause":
            speaker.set_paused(None)
        elif command == "seek":
            speaker.seek(float(request.get("seconds") or 0))
        elif command == "skip":
            speaker.skip()
        elif command == "warm":
            threading.Thread(target=speaker.warm, args=(request["speech"],), daemon=True).start()
        elif command == "shutdown":
            self.running = False
        elif command != "status":
            return {"ok": False, "error": f"unknown command {command!r}"}
        return {"ok": True, "status": speaker.snapshot()}

    def tick(self, config: dict) -> None:
        """Called a few times a second: status, idle stream, idle exit, error reports."""
        snapshot = self.speaker.snapshot()
        status.write_playback(snapshot)
        if self.media is not None:
            self.media.update(snapshot, bool(config.get("media_keys", True)))
        status.refresh(config, snapshot)
        with self.output_lock:
            # Checked under the lock: a speak request that already queued an item keeps the stream open.
            if not self.speaker.busy() and time.time() - self.speaker.last_activity > 3:
                self.output.stop()
        keep_alive = self.keep_alive if self.keep_alive is not None else float(config.get("keep_alive_minutes") or 10) * 60
        if not self.speaker.busy() and time.time() - self.speaker.last_activity > keep_alive:
            self.running = False
        errors = self.speaker.errors[self.reported_errors:]
        if errors:
            self.reported_errors += len(errors)
            from .herdr import notify

            notify(errors[-1])


def serve(daemon: Daemon, socket_file: str) -> None:
    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request = json.loads(self.rfile.readline() or b"{}")
                response = daemon.handle(request)
            except Exception as error:  # answer every request, even a malformed one
                response = {"ok": False, "error": str(error)}
            try:
                self.wfile.write(json.dumps(response).encode() + b"\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client stopped waiting

    if os.path.exists(socket_file):
        os.unlink(socket_file)
    server = socketserver.ThreadingUnixStreamServer(socket_file, Handler)
    server.daemon_threads = True
    os.chmod(socket_file, 0o600)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        config_mtime, config = None, settings.load()
        while daemon.running:
            try:
                mtime = paths.CONFIG_FILE.stat().st_mtime
            except FileNotFoundError:
                mtime = None
            if mtime != config_mtime:
                config_mtime, config = mtime, settings.load()
            daemon.tick(config)
            # Media commands arrive on the main run loop, so wait there rather than sleep.
            daemon.media.wait(0.25) if daemon.media is not None else time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()
        if os.path.exists(socket_file):
            os.unlink(socket_file)
        daemon.output.stop()
        if daemon.media is not None:
            daemon.media.close()
        status.write_playback({"state": "idle"})
        status.refresh(settings.load(), {"state": "idle"})


def main() -> int:
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    # One player per user: the lock is held for the daemon's lifetime.
    lock = open(paths.STATE_DIR / "speakd.lock", "a")  # noqa: SIM115  (held until the process exits)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    speaker = Speaker()
    output_kind = os.environ.get("HERDR_SPEAK_OUTPUT", "sounddevice")
    output = NullOutput(speaker.fill, float(os.environ.get("HERDR_SPEAK_SPEEDUP", "1"))) if output_kind == "null" \
        else SoundDeviceOutput(speaker.fill)
    keep_alive = os.environ.get("HERDR_SPEAK_KEEP_ALIVE")
    media = None
    if output_kind != "null" and os.environ.get("HERDR_SPEAK_MEDIA", "1") != "0":
        from .media import MediaControls

        media = MediaControls(speaker, log)
    daemon = Daemon(speaker, output, float(keep_alive) if keep_alive else None, media)
    warm = os.environ.get("HERDR_SPEAK_WARM")
    if warm:
        try:
            threading.Thread(target=speaker.warm, args=(json.loads(warm),), daemon=True).start()
        except ValueError:
            pass
    log(f"started (pid {os.getpid()})")
    try:
        serve(daemon, str(paths.socket_path()))
    finally:
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
