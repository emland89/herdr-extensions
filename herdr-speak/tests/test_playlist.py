"""A pane's responses as a playlist: turns, play, previous, next, and the mini player's pane."""

import unittest
from unittest import mock

from herdr_speak import mini, playlist, transcripts
from tests.support import isolate, write_jsonl

RESPONSES = ["First answer.", "Second answer.", "Third answer."]


def pi(role, text):
    return {"type": "message", "message": {"role": role, "content": [{"type": "text", "text": text}]}}


class TurnsTest(unittest.TestCase):
    def test_pi_keeps_the_last_text_of_each_turn(self):
        path = write_jsonl(self, [pi("user", "q1"), pi("assistant", "working on it"), pi("assistant", "one"),
                                  pi("user", "q2"), pi("assistant", "two"), pi("user", "q3")])
        self.assertEqual(transcripts.pi_responses(path), ["one", "two"])

    def test_claude_turns_start_at_typed_prompts_only(self):
        def user(content, **extra):
            return dict({"type": "user", "message": {"role": "user", "content": content}}, **extra)

        def assistant(message_id, text):
            return {"type": "assistant", "message": {"id": message_id, "content": [{"type": "text", "text": text}]}}

        path = write_jsonl(self, [
            user("first question"), assistant("a", "Let me look."), user([{"type": "tool_result", "content": "x"}]),
            assistant("b", "Answer one."), user("caveat", isMeta=True), user("second question"),
            assistant("c", "Answer two, part one."), assistant("c", "Part two."),
        ])
        self.assertEqual(transcripts.claude_responses(path), ["Answer one.", "Answer two, part one.\n\nPart two."])

    def test_codex_turns_start_at_task_started(self):
        def event(kind, **payload):
            return {"type": "event_msg", "payload": dict(payload, type=kind)}

        path = write_jsonl(self, [event("task_started"), event("task_complete", last_agent_message="one"),
                                  event("task_started"), event("task_complete", last_agent_message="two")])
        self.assertEqual(transcripts.codex_responses(path), ["one", "two"])


class PlaylistTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        patches = {
            "responses": mock.patch("herdr_speak.playlist.responses", return_value=list(RESPONSES)),
            "agent": mock.patch("herdr_speak.herdr.agent_info", return_value={"agent": "pi"}),
            "title": mock.patch("herdr_speak.herdr.pane_title", return_value="Pi in work"),
            "speak": mock.patch("herdr_speak.client.speak"),
            "control": mock.patch("herdr_speak.client.control", return_value=True),
            "playback": mock.patch("herdr_speak.client.playback", return_value={"state": "idle"}),
        }
        self.mocks = {name: patch.start() for name, patch in patches.items()}
        for patch in patches.values():
            self.addCleanup(patch.stop)

    def playing(self, index, position=1.0, queued=0):
        self.mocks["playback"].return_value = {"state": "playing", "position": position, "queued": queued,
                                               "track": {"pane": "w1:p1", "index": index, "count": 3}}

    def spoken(self):
        call = self.mocks["speak"].call_args
        return call[0][0], call[1]["track"]

    def test_play_reads_the_newest_response_with_its_track(self):
        track = playlist.play("w1:p1")
        self.assertEqual(track, {"pane": "w1:p1", "index": 2, "count": 3})
        self.assertEqual(self.spoken(), ("Third answer.", track))
        self.assertEqual(playlist.last_track(), track)

    def test_play_without_responses_says_so(self):
        self.mocks["responses"].return_value = []
        with self.assertRaisesRegex(playlist.NoTrack, "No response"):
            playlist.play("w1:p1")

    def test_previous_restarts_after_the_first_seconds(self):
        self.playing(2, position=12.0)
        self.assertEqual(playlist.previous("w1:p1"), "")
        self.mocks["control"].assert_called_once_with("seek", seconds=-1e9)
        self.mocks["speak"].assert_not_called()

    def test_previous_early_on_plays_the_response_before(self):
        self.playing(2, position=1.0)
        playlist.previous("w1:p2")  # what's playing wins over the focused pane
        self.assertEqual(self.spoken(), ("Second answer.", {"pane": "w1:p1", "index": 1, "count": 3}))

    def test_previous_at_the_first_response_restarts_it(self):
        self.playing(0)
        self.assertIn("first", playlist.previous())
        self.mocks["control"].assert_called_once_with("seek", seconds=-1e9)

    def test_after_playback_ends_previous_continues_from_the_last_response(self):
        playlist.play("w1:p1", 1)
        self.assertEqual(playlist.previous("w1:p1"), "")
        self.assertEqual(self.spoken()[1]["index"], 0)

    def test_idle_on_another_pane_starts_from_its_newest(self):
        playlist.play("w1:p1", 0)  # last heard: a different pane
        playlist.previous("w2:p5")
        self.assertEqual(self.spoken()[1], {"pane": "w2:p5", "index": 1, "count": 3})

    def test_next_plays_the_queue_first(self):
        self.playing(1, queued=1)
        playlist.next_response("w1:p1")
        self.mocks["control"].assert_called_once_with("skip")
        self.mocks["speak"].assert_not_called()

    def test_next_plays_the_following_response(self):
        self.playing(0)
        playlist.next_response("w1:p1")
        self.assertEqual(self.spoken(), ("Second answer.", {"pane": "w1:p1", "index": 1, "count": 3}))

    def test_next_after_the_newest_ends_playback(self):
        self.playing(2)
        self.assertIn("latest", playlist.next_response("w1:p1"))
        self.mocks["control"].assert_called_once_with("skip")

    def test_next_when_idle_reads_the_newest(self):
        playlist.next_response("w1:p1")
        self.assertEqual(self.spoken()[1]["index"], 2)

    def test_without_a_pane_there_is_nothing_to_step_through(self):
        self.assertIn("agent pane", playlist.previous())
        self.assertIn("agent pane", playlist.next_response())


class MiniTargetTest(unittest.TestCase):
    PANES = [
        {"pane_id": "w1:p1", "tab_id": "w1:t1", "agent": "claude", "focused": False},
        {"pane_id": "w1:p2", "tab_id": "w1:t1", "agent": "opencode", "focused": False},
        {"pane_id": "w1:p3", "tab_id": "w1:t1", "focused": False},  # a shell
        {"pane_id": "w1:p9", "tab_id": "w1:t1", "focused": False},  # the mini player
        {"pane_id": "w2:p1", "tab_id": "w2:t1", "agent": "pi", "focused": False},
    ]

    def pick(self, focused=None, current=None):
        panes = [dict(p, focused=p["pane_id"] == focused) for p in self.PANES]
        chosen = mini.pick_target(panes, "w1:p9", "w1:t1", current)
        return chosen and chosen["pane_id"]

    def test_follows_the_focused_agent_pane_in_its_tab(self):
        self.assertEqual(self.pick(focused="w1:p2"), "w1:p2")

    def test_keeps_its_pane_while_the_mini_player_or_a_shell_has_focus(self):
        self.assertEqual(self.pick(focused="w1:p9", current="w1:p2"), "w1:p2")
        self.assertEqual(self.pick(focused="w1:p3", current="w1:p2"), "w1:p2")

    def test_ignores_other_tabs_and_starts_with_the_first_agent(self):
        self.assertEqual(self.pick(focused="w2:p1"), "w1:p1")


if __name__ == "__main__":
    unittest.main()
