"""The player's queue, pause, seek, and socket protocol, with a fake engine and no sound device.

Needs numpy, so it runs with the runtime's Python (scripts/test.sh) or in CI.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest

from tests.support import isolate

try:
    import numpy as np

    from herdr_speak import daemon
except ImportError:  # the plugin launcher's Python has no numpy
    np = None

RATE = 24000


class FakeEngine:
    """One second of a constant tone per paragraph; slow=True lets tests observe buffering."""

    def __init__(self, slow: float = 0.0, fail_on: str = ""):
        self.slow = slow
        self.fail_on = fail_on

    def synthesize(self, text, language, voice, speed):
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("engine exploded")
        time.sleep(self.slow)
        return np.full(RATE, 0.5, dtype=np.float32)


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@unittest.skipIf(np is None, "needs numpy (run with the runtime Python)")
class SpeakerTest(unittest.TestCase):
    def setUp(self):
        isolate(self)  # engine errors are logged to the state directory

    def make(self, **engine):
        speaker = daemon.Speaker(engines={"say": FakeEngine(**engine)})
        self.speech = {"engine": "say", "voice": "x", "speed": 1.0, "language": "en-us"}
        return speaker

    def play(self, speaker, seconds: float) -> np.ndarray:
        out = np.zeros(int(seconds * RATE), dtype=np.float32)
        speaker.fill(out)
        return out

    def test_plays_paragraphs_in_order_then_goes_idle(self):
        speaker = self.make()
        speaker.speak("one\n\ntwo", "T", self.speech, queue=False)
        self.assertTrue(wait_for(lambda: speaker.items and speaker.items[0].done))
        # Two 1 s paragraphs plus a 0.25 s pause after each.
        self.assertEqual(speaker.items[0].length, int(2.5 * RATE))
        self.assertGreater(self.play(speaker, 2.5).max(), 0)
        self.play(speaker, 0.1)
        self.assertEqual(speaker.snapshot(), {"state": "idle"})

    def test_pause_outputs_silence_and_keeps_position(self):
        speaker = self.make()
        speaker.speak("one", "T", self.speech, queue=False)
        wait_for(lambda: speaker.items[0].done)
        self.play(speaker, 0.5)
        speaker.set_paused(True)
        self.assertEqual(self.play(speaker, 0.5).max(), 0)
        self.assertEqual(speaker.snapshot()["state"], "paused")
        self.assertAlmostEqual(speaker.snapshot()["position"], 0.5, places=2)
        speaker.set_paused(None)
        self.assertGreater(self.play(speaker, 0.1).max(), 0)

    def test_seek_is_clamped_to_synthesized_audio(self):
        speaker = self.make()
        speaker.speak("one", "T", self.speech, queue=False)
        wait_for(lambda: speaker.items[0].done)
        speaker.seek(-5)
        self.assertEqual(speaker.snapshot()["position"], 0)
        speaker.seek(5)
        self.assertAlmostEqual(speaker.snapshot()["position"], 1.25, places=2)

    def test_queue_skip_and_replace(self):
        speaker = self.make()
        speaker.speak("first", "A", self.speech, queue=False)
        speaker.speak("second", "B", self.speech, queue=True)
        self.assertEqual(speaker.snapshot()["queued"], 1)
        speaker.skip()
        self.assertEqual(speaker.snapshot()["title"], "B")
        speaker.speak("third", "C", self.speech, queue=False)  # a manual read replaces the queue
        self.assertEqual((speaker.snapshot()["title"], speaker.snapshot()["queued"]), ("C", 0))
        speaker.stop()
        self.assertEqual(speaker.snapshot(), {"state": "idle"})

    def test_progress_never_slides_back_while_paragraphs_arrive(self):
        speaker = self.make(slow=0.05)
        speaker.speak("\n\n".join(["x" * 14] * 6), "T", self.speech, queue=False)
        fractions = []
        while not (speaker.items and speaker.items[0].done):
            snapshot = speaker.snapshot()
            if snapshot.get("duration"):
                fractions.append(snapshot["position"] / snapshot["duration"])
            self.play(speaker, 0.05)
            time.sleep(0.01)
        self.assertTrue(fractions)
        # The estimate may settle a little, but never pulls the bar back noticeably.
        self.assertTrue(all(b >= a - 0.02 for a, b in zip(fractions, fractions[1:])), fractions)

    def test_paused_time_is_reported_for_media_keys(self):
        speaker = self.make()
        speaker.speak("one", "T", self.speech, queue=False)
        speaker.set_paused(True)
        time.sleep(0.05)
        self.assertGreater(speaker.snapshot()["paused_seconds"], 0.04)
        speaker.set_paused(False)
        self.assertEqual(speaker.snapshot()["paused_seconds"], 0.0)
        speaker.warm(self.speech)  # a non-Kokoro engine just loads

    def test_reports_buffering_while_synthesizing(self):
        speaker = self.make(slow=0.3)
        speaker.speak("one", "T", self.speech, queue=False)
        self.assertEqual(speaker.snapshot()["state"], "buffering")
        self.assertEqual(self.play(speaker, 0.1).max(), 0)

    def test_engine_errors_drop_the_item_and_are_reported(self):
        speaker = self.make(fail_on="boom")
        speaker.speak("boom", "Bad", self.speech, queue=False)
        speaker.speak("fine", "Good", self.speech, queue=True)
        self.assertTrue(wait_for(lambda: speaker.errors))
        self.play(speaker, 0.1)
        self.assertEqual(speaker.snapshot()["title"], "Good")
        self.assertEqual(speaker.errors, ["engine exploded"])


@unittest.skipIf(np is None, "needs numpy (run with the runtime Python)")
class ItemTest(unittest.TestCase):
    def test_reads_across_chunks(self):
        item = daemon.Item("T", ["x"], {}, "manual")
        item.append(np.arange(0, 5, dtype=np.float32))
        item.append(np.arange(5, 8, dtype=np.float32))
        out = np.zeros(4, dtype=np.float32)
        self.assertEqual(item.read_into(out, 3), 4)
        self.assertEqual(out.tolist(), [3, 4, 5, 6])
        self.assertEqual(item.read_into(out, 7), 1)
        self.assertEqual(item.read_into(out, 8), 0)


class CountingOutput:
    """Records how many streams are open at once; opening takes a while, like a real device."""

    def __init__(self):
        self.open = 0
        self.most = 0
        self.lock = threading.Lock()

    def start(self):
        if self.open == 0:
            time.sleep(0.05)
            with self.lock:
                self.open += 1
                self.most = max(self.most, self.open)

    def stop(self):
        if self.open:
            time.sleep(0.05)
            with self.lock:
                self.open -= 1


@unittest.skipIf(np is None, "needs numpy (run with the runtime Python)")
class OutputRaceTest(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def test_simultaneous_speak_requests_open_one_stream(self):
        speaker = daemon.Speaker(engines={"say": FakeEngine()})
        output = CountingOutput()
        server = daemon.Daemon(speaker, output, keep_alive=60)
        speech = {"engine": "say", "voice": "x", "speed": 1.0, "language": "en-us"}
        threads = [threading.Thread(target=server.handle, args=({"command": "speak", "text": "hi", "title": str(i),
                                                                 "speech": speech, "queue": True},)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(output.most, 1)

    def test_idle_stop_never_closes_a_stream_with_queued_audio(self):
        speaker = daemon.Speaker(engines={"say": FakeEngine()})
        output = CountingOutput()
        server = daemon.Daemon(speaker, output, keep_alive=60)
        speaker.last_activity = time.time() - 10  # idle long enough to close the stream
        speech = {"engine": "say", "voice": "x", "speed": 1.0, "language": "en-us"}
        server.handle({"command": "speak", "text": "hi", "title": "T", "speech": speech})
        server.tick({})
        self.assertEqual(output.open, 1)


@unittest.skipIf(np is None, "needs numpy (run with the runtime Python)")
class ProtocolTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        from herdr_speak import paths

        speaker = daemon.Speaker(engines={"say": FakeEngine()})
        self.daemon = daemon.Daemon(speaker, daemon.NullOutput(speaker.fill, speedup=4), keep_alive=60)
        self.socket = str(paths.socket_path())
        paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=daemon.serve, args=(self.daemon, self.socket), daemon=True)
        self.thread.start()
        self.assertTrue(wait_for(self.connectable))
        self.addCleanup(self.shutdown)

    def connectable(self):
        # The socket file appears at bind(), a moment before the server listens.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            try:
                connection.connect(self.socket)
            except OSError:
                return False
        return True

    def shutdown(self):
        self.daemon.running = False
        self.thread.join(5)

    def send(self, **payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(self.socket)
            connection.sendall(json.dumps(payload).encode() + b"\n")
            return json.loads(connection.makefile().readline())

    def test_speak_status_pause_and_finish(self):
        speech = {"engine": "say", "voice": "x", "speed": 1.0, "language": "en-us"}
        response = self.send(command="speak", text="hello\n\nworld", title="Test", speech=speech)
        self.assertTrue(response["ok"])
        self.assertTrue(wait_for(lambda: self.send(command="status")["status"]["state"] == "playing"))
        self.assertEqual(self.send(command="toggle-pause")["status"]["state"], "paused")
        self.send(command="resume")
        # 2.5 s of audio at 4x speed finishes well within the timeout.
        self.assertTrue(wait_for(lambda: self.send(command="status")["status"]["state"] == "idle", 5))

    def test_status_file_and_statusline_follow_playback(self):
        from herdr_speak import paths

        speech = {"engine": "say", "voice": "x", "speed": 1.0, "language": "en-us"}
        self.send(command="speak", text="hello", title="Claude", speech=speech)
        self.assertTrue(wait_for(lambda: paths.STATUSLINE_FILE.exists()
                                 and paths.STATUSLINE_FILE.read_text().startswith("▶ Claude")))

    def test_unknown_command_is_an_error(self):
        self.assertEqual(self.send(command="dance")["ok"], False)
        self.assertEqual(self.send()["ok"], False)


if __name__ == "__main__":
    unittest.main()
