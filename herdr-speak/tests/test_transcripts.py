import json
import tempfile
import unittest
from pathlib import Path

from herdr_speak import transcripts
from tests.support import write_jsonl


class TranscriptTest(unittest.TestCase):
    def test_pi_returns_last_assistant_text(self):
        path = write_jsonl(self, [
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}]}},
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "final"}]}},
        ])
        self.assertEqual(transcripts.last_pi_message(path), "final")

    def test_claude_joins_blocks_of_last_message_and_skips_sidechains(self):
        path = write_jsonl(self, [
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "old"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "part one"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "part two"}]}},
            {"type": "assistant", "isSidechain": True, "message": {"id": "s", "content": [{"type": "text", "text": "sub"}]}},
        ])
        self.assertEqual(transcripts.last_claude_message(path), "part one\n\npart two")

    def test_codex_prefers_latest_message(self):
        path = write_jsonl(self, [
            {"type": "session_meta", "payload": {"cwd": "/tmp"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                   "content": [{"type": "output_text", "text": "interim"}]}},
            {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "done"}},
        ])
        self.assertEqual(transcripts.last_codex_message(path), "done")

    def test_skips_corrupt_lines(self):
        path = write_jsonl(self, [{"type": "message", "message": {"role": "assistant", "content": "ok"}}])
        with open(path, "a") as handle:
            handle.write("{not json\n")
        self.assertEqual(transcripts.last_pi_message(path), "ok")

    def test_ignores_json_that_is_not_an_entry(self):
        path = write_jsonl(self, [[1, 2], "text", 3, None,
                                  {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": 5}]}},
                                  {"type": "message", "message": {"role": "assistant", "content": "ok"}}])
        self.assertEqual(transcripts.last_pi_message(path), "ok")
        self.assertIsNone(transcripts.last_claude_message(path))
        codex = write_jsonl(self, [{"type": "event_msg", "payload": "oops"}, [1],
                                   {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": 7}}])
        self.assertIsNone(transcripts.last_codex_message(codex))

    def test_finds_codex_rollout_by_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            day = home / ".codex/sessions/2026/11/12"
            day.mkdir(parents=True)
            (day / "rollout-a.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"cwd": "/other"}}) + "\n")
            (day / "rollout-b.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"cwd": "/work"}}) + "\n")
            self.assertEqual(transcripts.codex_transcript(None, "/work", home).name, "rollout-b.jsonl")
            self.assertIsNone(transcripts.codex_transcript(None, "/missing", home))

    def test_unsupported_and_unreported_agents_explain_why(self):
        with self.assertRaisesRegex(RuntimeError, "isn't supported"):
            transcripts.last_response({"agent": "opencode"})
        with self.assertRaisesRegex(RuntimeError, "hasn't reported a session"):
            transcripts.last_response({"agent": "pi"})


if __name__ == "__main__":
    unittest.main()
