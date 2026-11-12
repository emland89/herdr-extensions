"""Media key and Control Center mapping, without PyObjC."""

import unittest

from herdr_speak import media


class FakeSpeaker:
    def __init__(self, busy=True, position=12.0):
        self._busy = busy
        self.position = position
        self.calls = []

    def busy(self):
        return self._busy

    def snapshot(self):
        return {"state": "playing", "position": self.position}

    def set_paused(self, value):
        self.calls.append(("paused", value))

    def skip(self):
        self.calls.append(("skip",))

    def seek(self, seconds):
        self.calls.append(("seek", seconds))


class HandleCommandTest(unittest.TestCase):
    def test_commands_map_to_player_actions(self):
        speaker = FakeSpeaker()
        for name in ("toggle", "play", "pause", "next", "previous", "forward", "back"):
            self.assertTrue(media.handle_command(speaker, name))
        self.assertTrue(media.handle_command(speaker, "position", 30.0))
        self.assertEqual(speaker.calls, [("paused", None), ("paused", False), ("paused", True), ("skip",),
                                         ("seek", -1e9), ("seek", 5), ("seek", -5), ("seek", 18.0)])

    def test_nothing_happens_when_idle(self):
        speaker = FakeSpeaker(busy=False)
        self.assertFalse(media.handle_command(speaker, "toggle"))
        self.assertEqual(speaker.calls, [])

    def test_unknown_command(self):
        self.assertFalse(media.handle_command(FakeSpeaker(), "shuffle"))


class NowPlayingTest(unittest.TestCase):
    def test_fields(self):
        fields = media.now_playing({"state": "paused", "title": "Claude in api", "position": 3, "duration": 40})
        self.assertEqual(fields, {"title": "Claude · api", "artist": "Speak", "duration": 40.0, "elapsed": 3.0,
                                  "rate": 0.0, "paused": True})
        self.assertEqual(media.now_playing({"state": "playing", "title": "Selection"})["title"], "Selection")
        self.assertIsNone(media.now_playing({"state": "idle"}))

    def test_lets_go_of_the_keys_after_a_long_pause(self):
        paused = {"state": "paused", "title": "T", "position": 3, "duration": 40}
        self.assertIsNotNone(media.now_playing(dict(paused, paused_seconds=60)))
        self.assertIsNone(media.now_playing(dict(paused, paused_seconds=media.RELEASE_AFTER_PAUSE + 1)))


if __name__ == "__main__":
    unittest.main()
