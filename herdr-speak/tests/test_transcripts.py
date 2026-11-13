import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def opencode_db(self, schema: str, rows) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        home = Path(directory.name)
        root = home / ".local/share/opencode"
        root.mkdir(parents=True)
        db = sqlite3.connect(root / "opencode.db")
        db.executescript(schema)
        for table, values in rows:
            db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(values))})", values)
        db.commit()
        db.close()
        return home

    def test_opencode_2_reads_the_last_assistant_text(self):
        def message(seq, kind, content):
            return "session_message", (f"m{seq}", "s1", kind, seq, json.dumps({"content": content}))

        home = self.opencode_db("CREATE TABLE session_message (id, session_id, type, seq, data);", [
            message(1, "assistant", [{"type": "text", "text": "old"}]),
            message(2, "user", [{"type": "text", "text": "question"}]),
            message(3, "assistant", [{"type": "reasoning", "text": "thinking"}, {"type": "text", "text": "answer"}]),
            message(4, "assistant", [{"type": "tool", "name": "shell"}]),
            message(5, "idle", {}),
            ("session_message", ("x", "s2", "assistant", 9, json.dumps({"content": [{"type": "text", "text": "other"}]}))),
            ("session_message", ("y", "s1", "assistant", 0, "{not json")),
        ])
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": ""}):
            self.assertEqual(transcripts.last_opencode_message("s1", home), "answer")
            self.assertIsNone(transcripts.last_opencode_message("missing", home))

    def test_opencode_1_reads_parts_and_skips_synthetic_ones(self):
        home = self.opencode_db("CREATE TABLE message (id, session_id, time_created, data);"
                                "CREATE TABLE part (id, message_id, data);", [
            ("message", ("m1", "s1", 1, json.dumps({"role": "assistant"}))),
            ("part", ("p1", "m1", json.dumps({"type": "reasoning", "text": "hmm"}))),
            ("part", ("p2", "m1", json.dumps({"type": "text", "text": "seventy-three"}))),
            ("message", ("m2", "s1", 2, json.dumps({"role": "user"}))),
            ("part", ("p3", "m2", json.dumps({"type": "text", "text": "tool output", "synthetic": True}))),
        ])
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": ""}):
            self.assertEqual(transcripts.last_opencode_message("s1", home), "seventy-three")

    def test_opencode_without_a_database_has_no_response(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"XDG_DATA_HOME": ""}):
            self.assertIsNone(transcripts.last_opencode_message("s1", Path(directory)))

    def test_pending_request_is_the_newest_call_without_a_result(self):
        claude = write_jsonl(self, [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Read", "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "git push", "description": "Push it"}}]}},
        ])
        self.assertEqual(transcripts._claude_pending(claude), ("Bash", {"command": "git push", "description": "Push it"}))
        pi = write_jsonl(self, [
            {"type": "message", "message": {"role": "assistant", "content": [
                {"type": "toolCall", "id": "1", "name": "bash", "arguments": {"command": "rm -rf build"}}]}},
        ])
        self.assertEqual(transcripts._pi_pending(pi), ("bash", {"command": "rm -rf build"}))
        codex = write_jsonl(self, [
            {"type": "response_item", "payload": {"type": "function_call", "call_id": "x", "name": "shell", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "x"}},
        ])
        self.assertIsNone(transcripts._codex_pending(codex))

    def test_opencode_pending_tool_is_one_that_has_not_finished(self):
        def row(seq, status):
            content = [{"type": "tool", "name": "shell", "state": {"status": status, "input": {"command": "make"}}}]
            return ("session_message", (f"m{seq}", "s1", "assistant", seq, json.dumps({"content": content})))

        home = self.opencode_db("CREATE TABLE session_message (id, session_id, type, seq, data);",
                                [row(1, "completed"), row(2, "pending")])
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": ""}):
            self.assertEqual(transcripts._opencode_pending("s1", home), ("shell", {"command": "make"}))

    def test_requests_are_described_in_plain_words(self):
        describe = transcripts.describe_request
        self.assertEqual(describe("Bash", {"command": "git push", "description": "Push the branch"}),
                         "wants to run a command: push the branch")
        self.assertEqual(describe("Bash", {"command": "cd app && FOO=1 npm test"}), "wants to run npm")
        self.assertEqual(describe("exec", "const x = 1"), "wants to run code")
        self.assertEqual(describe("Edit", {"file_path": "/x/src/config.py"}), "wants to edit config.py")
        self.assertEqual(describe("WebFetch", {"url": "https://docs.github.com/en"}), "wants to fetch from docs.github.com")
        self.assertEqual(describe("AskUserQuestion", {"questions": [{"question": "Which one?", "options": [
            {"label": "A"}, {"label": "B"}]}]}), "asks: Which one? Options: A, B.")
        self.assertEqual(describe("ExitPlanMode", {}), "has a plan ready for you to review")
        self.assertEqual(describe("mcp__gitea__issue_write", {}), "wants to use gitea issue write")

    def test_unsupported_and_unreported_agents_explain_why(self):
        with self.assertRaisesRegex(RuntimeError, "isn't supported"):
            transcripts.last_response({"agent": "aider"})
        with self.assertRaisesRegex(RuntimeError, "hasn't reported a session"):
            transcripts.last_response({"agent": "opencode"})
        with self.assertRaisesRegex(RuntimeError, "hasn't reported a session"):
            transcripts.last_response({"agent": "pi"})


if __name__ == "__main__":
    unittest.main()
