import json
import unittest
from unittest import mock

from herdr_speak import autoread, paths
from tests.support import isolate, write_jsonl


def event(pane: str, state: str) -> str:
    return json.dumps({"event": "pane_agent_status_changed",
                       "data": {"type": "pane_agent_status_changed", "pane_id": pane, "agent_status": state}})


class ParsingTest(unittest.TestCase):
    def test_parses_herdr_event(self):
        self.assertEqual(autoread.parse_status_event(event("w1:p2", "done")), ("w1:p2", "done"))
        self.assertEqual(autoread.parse_status_event("not json"), (None, None))

    def test_reads_only_after_a_finished_turn(self):
        self.assertTrue(autoread.should_read("working", "done"))
        self.assertTrue(autoread.should_read("working", "idle"))
        self.assertFalse(autoread.should_read("done", "idle"))  # the user viewed a finished pane
        self.assertFalse(autoread.should_read(None, "idle"))
        self.assertFalse(autoread.should_read("working", "blocked"))

    def test_scope(self):
        self.assertTrue(autoread.in_scope("all", True))
        self.assertFalse(autoread.in_scope("background", True))
        self.assertTrue(autoread.in_scope("background", False))
        self.assertFalse(autoread.in_scope("focused", False))


def reply(text: str) -> dict:
    return {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class HandleEventTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        self.transcript = write_jsonl(self, [reply("An older answer.")])
        self.agent = {"agent": "pi", "focused": False, "workspace_id": "w1",
                      "agent_session": {"kind": "path", "value": str(self.transcript)}}
        patches = [
            mock.patch("herdr_speak.herdr.agent_info", return_value=self.agent),
            mock.patch("herdr_speak.herdr.pane_title", return_value="Pi in work"),
            mock.patch("herdr_speak.client.speak"),
            mock.patch("herdr_speak.autoread.time.sleep"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        from herdr_speak import client

        self.speak = client.speak

    def send(self, config: dict, *states: str) -> None:
        for state in states:
            autoread.handle_event(config, event("w1:p1", state))

    def answer(self, text: str) -> None:
        with open(self.transcript, "a") as handle:
            handle.write(json.dumps(reply(text)) + "\n")

    def turn(self, config: dict, text: str, end: str = "done") -> None:
        self.send(config, "working")
        self.answer(text)
        self.send(config, end)

    def test_off_by_default_does_nothing(self):
        self.turn({"auto_read": False}, "**Done**.")
        self.speak.assert_not_called()

    def test_speaks_finished_turn_once_with_announcement(self):
        config = {"auto_read": True, "announce": True, "auto_panes": "all", "language": "en-us"}
        self.turn(config, "**Done**.")
        self.send(config, "idle")  # viewing the finished pane doesn't read it again
        self.speak.assert_called_once()
        text, title = self.speak.call_args[0][:2]
        self.assertEqual(text, "Pi in work.\n\nDone.")
        self.assertEqual(title, "Pi in work")
        self.assertEqual(self.speak.call_args[1], {"queue": True, "source": "auto"})

    def test_waits_for_the_transcript_instead_of_rereading_the_old_answer(self):
        config = {"auto_read": True, "announce": False}
        self.send(config, "working", "done")  # the transcript never caught up
        self.speak.assert_not_called()

    def test_each_turn_is_read_and_a_repeat_is_not(self):
        config = {"auto_read": True, "announce": False}
        self.turn(config, "First.")
        self.turn(config, "Second.")
        self.send(config, "working", "done")  # no new answer this time
        self.assertEqual([c[0][0] for c in self.speak.call_args_list], ["First.", "Second."])

    def test_not_marked_spoken_when_the_player_fails(self):
        config = {"auto_read": True, "announce": False}
        self.speak.side_effect = RuntimeError("player down")
        with self.assertRaises(RuntimeError):
            self.turn(config, "Important.")
        self.assertNotIn("spoken", json.loads(paths.PANES_FILE.read_text())["w1:p1"])

    def test_scope_skips_focused_pane(self):
        self.agent["focused"] = True
        self.turn({"auto_read": True, "auto_panes": "background"}, "Hi.")
        self.speak.assert_not_called()

    def test_announces_blocked_when_enabled(self):
        self.send({"auto_read": True, "announce_blocked": True, "language": "en-us"}, "working", "blocked")
        self.assertEqual(self.speak.call_args[0][0], "Pi in work needs your input.")


if __name__ == "__main__":
    unittest.main()
