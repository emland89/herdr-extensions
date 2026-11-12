"""The `say` fallback used before setup: queued auto-reads take turns and stop drops them."""

import threading
import time
import unittest
from unittest import mock

from herdr_speak import client, paths
from tests.support import isolate


class FakeSay:
    """Stands in for the `say` process: one utterance at a time, finished by the test."""

    def __init__(self):
        self.playing = None
        self.started = []
        self.lock = threading.Lock()

    def pid(self):
        return 1 if self.playing else None

    def start(self, text, title, speech):
        with self.lock:
            assert self.playing is None, f"{text!r} cut off {self.playing!r}"
            self.playing = text
            self.started.append(text)

    def finish(self):
        self.playing = None


class FallbackQueueTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        self.say = FakeSay()
        for target, replacement in (("_fallback_pid", self.say.pid), ("_fallback_start", self.say.start),
                                    ("player_running", lambda: False), ("start_player", lambda: False),
                                    ("_fallback_stop", lambda: self.say.finish() or False)):
            patch = mock.patch.object(client, target, side_effect=replacement)
            patch.start()
            self.addCleanup(patch.stop)
        self.speech = {"engine": "say", "voice": "Samantha", "speed": 1.0}

    def queue(self, text):
        thread = threading.Thread(target=client._fallback_speak, args=(text, text, self.speech, True))
        thread.start()
        return thread

    def test_queued_speech_takes_turns_without_cutting_off(self):
        self.say.start("current", "", {})
        waiting = [self.queue("first"), self.queue("second")]
        time.sleep(0.7)  # the waiters poll every 0.5 s
        self.assertEqual(self.say.started, ["current"])
        self.say.finish()
        self.assertTrue(self._wait(lambda: len(self.say.started) == 2))
        time.sleep(0.7)
        self.assertEqual(len(self.say.started), 2)  # the other one still waits
        self.say.finish()
        for thread in waiting:
            thread.join(3)
        self.assertEqual(sorted(self.say.started[1:]), ["first", "second"])

    def test_stop_drops_queued_speech(self):
        self.say.start("current", "", {})
        waiting = self.queue("later")
        time.sleep(0.05)
        client.stop()  # the user stops speech: "later" must not start afterwards
        waiting.join(3)
        self.assertFalse(waiting.is_alive())
        self.assertEqual(self.say.started, ["current"])
        self.assertTrue((paths.STATE_DIR / "fallback.stopped").exists())

    @staticmethod
    def _wait(predicate, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False


class WarmTest(unittest.TestCase):
    def test_warm_is_a_no_op_without_the_runtime(self):
        isolate(self)
        with mock.patch("subprocess.Popen") as popen, mock.patch.object(client, "request") as request:
            client.warm({"engine": "auto", "language": "en-us", "speed": 1.0, "model": "full"})
        popen.assert_not_called()
        request.assert_not_called()

    def test_warm_tolerates_partial_settings(self):
        isolate(self)
        client.warm({"auto_read": True})  # what auto-read's tests and old configs may pass


if __name__ == "__main__":
    unittest.main()
