"""Find an agent's last response in its own session transcript.

Reading transcripts instead of the screen gets the full response, including
parts scrolled out of view, without terminal decoration. Transcript content is
untrusted data: it is only ever spoken, never executed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

from .paths import HOME


def _jsonl(path: Path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):  # anything else isn't a transcript entry
                yield entry


def _text_blocks(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") in ("text", "output_text") and isinstance(block.get("text"), str)
    ]
    return "\n\n".join(part for part in parts if part.strip())


class _Turns:
    """Collects one response per turn: the last text the agent wrote before the next prompt."""

    def __init__(self):
        self.responses: List[str] = []
        self.current: Optional[str] = None

    def prompt(self) -> None:
        if self.current:
            self.responses.append(self.current)
        self.current = None

    def text(self, text) -> None:
        if isinstance(text, str) and text.strip():
            self.current = text

    def done(self) -> List[str]:
        self.prompt()
        return self.responses


def pi_responses(path: Path) -> List[str]:
    turns = _Turns()
    for entry in _jsonl(path):
        message = entry.get("message")
        if entry.get("type") != "message" or not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            turns.prompt()
        elif message.get("role") == "assistant":
            turns.text(_text_blocks(message.get("content")))
    return turns.done()


def _claude_prompt(entry: dict) -> bool:
    """A prompt the user typed, not a tool result or an injected (meta) message."""
    message = entry.get("message")
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta") or not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) or (
        isinstance(content, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content))


def claude_responses(path: Path) -> List[str]:
    # One API message is stored as several entries (one per content block) sharing
    # message.id; a turn's response is the text blocks of its last message with text.
    turns, last_id, chunks = _Turns(), None, []
    for entry in _jsonl(path):
        if _claude_prompt(entry):
            turns.prompt()
            last_id, chunks = None, []
            continue
        message = entry.get("message")
        if entry.get("type") != "assistant" or entry.get("isSidechain") or not isinstance(message, dict):
            continue
        text = _text_blocks(message.get("content"))
        if not text.strip():
            continue
        if message.get("id") != last_id:
            last_id, chunks = message.get("id"), []
        chunks.append(text)
        turns.text("\n\n".join(chunks))
    return turns.done()


def codex_responses(path: Path) -> List[str]:
    turns = _Turns()
    for entry in _jsonl(path):
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "event_msg" and payload.get("type") == "task_started":
            turns.prompt()
        elif entry.get("type") == "event_msg" and payload.get("type") == "task_complete":
            turns.text(payload.get("last_agent_message"))
        elif entry.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            turns.text(_text_blocks(payload.get("content")))
    return turns.done()


def _last(responses: List[str]) -> Optional[str]:
    return responses[-1] if responses else None


def last_pi_message(path: Path) -> Optional[str]:
    return _last(pi_responses(path))


def last_claude_message(path: Path) -> Optional[str]:
    return _last(claude_responses(path))


def last_codex_message(path: Path) -> Optional[str]:
    return _last(codex_responses(path))


def claude_transcript(session_id: str, home: Path = HOME) -> Optional[Path]:
    matches = list((home / ".claude/projects").glob(f"*/{session_id}.jsonl"))
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def codex_transcript(session_id: Optional[str], cwd: Optional[str], home: Path = HOME) -> Optional[Path]:
    root = home / ".codex/sessions"
    if session_id:
        matches = list(root.glob(f"**/rollout-*{session_id}.jsonl"))
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    if not cwd:
        return None
    # No session reported: take the most recently written rollout for this directory.
    rollouts = sorted(root.glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in rollouts[:300]:
        payload = next(_jsonl(path), {}).get("payload")
        if isinstance(payload, dict) and payload.get("cwd") == cwd:
            return path
    return None


def opencode_databases(home: Path = HOME) -> List[Path]:
    """opencode's session databases, the default one first (other channels write opencode-<channel>.db)."""
    root = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / "opencode"
    others = sorted(root.glob("opencode-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [path for path in [root / "opencode.db", *others] if path.is_file()]


def _json(data):
    try:
        value = json.loads(data)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# The newest messages are enough: older turns are rarely replayed, and long sessions hold thousands.
OPENCODE_ROWS = 3000


def _opencode_v2(db: sqlite3.Connection, session_id: str) -> List[str]:
    # opencode 2: one row per message, its text, reasoning, and tool blocks in data.content
    # A turn ends when the session goes idle or a prompt arrives: the user's, or a goal's
    # "continue" message in goal mode, which can run for hours without one.
    rows = db.execute("SELECT type, data FROM session_message WHERE session_id = ? "
                      "AND type IN ('user', 'assistant', 'idle', 'synthetic') ORDER BY seq DESC LIMIT ?",
                      (session_id, OPENCODE_ROWS)).fetchall()
    turns = _Turns()
    for kind, data in reversed(rows):
        message = _json(data)
        if kind in ("user", "idle"):
            turns.prompt()
        elif message is None:
            continue
        elif kind == "assistant":
            turns.text(_text_blocks(message.get("content")))
        elif (message.get("metadata") or {}).get("source") == "goal":
            turns.prompt()
    return turns.done()


def _opencode_v1(db: sqlite3.Connection, session_id: str) -> List[str]:
    # opencode 1: messages and their parts in separate tables
    rows = db.execute("SELECT m.id, m.data, p.data FROM (SELECT id, data, time_created FROM message WHERE session_id = ? "
                      "ORDER BY time_created DESC, id DESC LIMIT ?) m LEFT JOIN part p ON p.message_id = m.id "
                      "ORDER BY m.time_created, m.id, p.id", (session_id, OPENCODE_ROWS)).fetchall()
    turns, current, parts = _Turns(), None, []

    def finish() -> None:
        if current is not None and current.get("role") == "assistant":
            turns.text(_text_blocks(parts))

    last_id = None
    for message_id, data, part_data in rows:
        if message_id != last_id:
            finish()
            last_id, current, parts = message_id, _json(data), []
            if current is not None and current.get("role") == "user":
                turns.prompt()
        part = _json(part_data)
        if part is not None and not part.get("synthetic") and not part.get("ignored"):
            parts.append(part)
    finish()
    return turns.done()


def opencode_responses(session_id: str, home: Path = HOME) -> List[str]:
    """An opencode session's responses, read from its SQLite database without writing to it."""
    for path in opencode_databases(home):
        try:
            db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            continue
        try:
            for reader in (_opencode_v2, _opencode_v1):
                try:
                    responses = reader(db, session_id)
                except sqlite3.OperationalError:  # this schema's tables don't exist in this database
                    continue
                if responses:
                    return responses
        except sqlite3.Error:
            continue
        finally:
            db.close()
    return []


def last_opencode_message(session_id: str, home: Path = HOME) -> Optional[str]:
    return _last(opencode_responses(session_id, home))


SUPPORTED_AGENTS = {"pi": "Pi", "claude": "Claude", "codex": "Codex", "opencode": "opencode"}


def responses(agent: dict) -> List[str]:
    """Every response of the agent described by `herdr agent get` (or a `pane list` entry), oldest first."""
    kind = agent.get("agent")
    value = (agent.get("agent_session") or {}).get("value")
    if kind == "pi" and value:
        return pi_responses(Path(value))
    if kind == "claude" and value:
        path = claude_transcript(value)
        return claude_responses(path) if path else []
    if kind == "codex":
        path = codex_transcript(value, agent.get("foreground_cwd") or agent.get("cwd"))
        return codex_responses(path) if path else []
    if kind == "opencode" and value:
        return opencode_responses(value)
    if kind in SUPPORTED_AGENTS:
        raise RuntimeError(f"Herdr hasn't reported a session for {SUPPORTED_AGENTS[kind]} in this pane yet")
    raise RuntimeError(f"Reading responses from {kind or 'this pane'} isn't supported")


# ---------------------------------------------------------------- what a blocked agent is asking

SHELL_TOOLS = {"bash", "shell", "exec_command", "execute", "exec", "local_shell"}
EDIT_TOOLS = {"edit", "multiedit", "write", "patch", "apply_patch", "notebookedit"}
QUESTION_TOOLS = {"askuserquestion", "question", "ask_user", "request_user_input"}


def _arguments(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {"input": value}
    return value if isinstance(value, dict) else {}


def _claude_pending(path: Path) -> Optional[tuple]:
    pending: dict = {}
    for entry in _jsonl(path):
        message = entry.get("message")
        if entry.get("isSidechain") or not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                pending[block.get("id")] = (block.get("name"), block.get("input"))
            elif block.get("type") == "tool_result":
                pending.pop(block.get("tool_use_id"), None)
    return list(pending.values())[-1] if pending else None


def _pi_pending(path: Path) -> Optional[tuple]:
    pending: dict = {}
    for entry in _jsonl(path):
        message = entry.get("message")
        if entry.get("type") != "message" or not isinstance(message, dict):
            continue
        if message.get("role") == "toolResult":
            pending.pop(message.get("toolCallId"), None)
        elif message.get("role") == "assistant" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    pending[block.get("id")] = (block.get("name"), block.get("arguments"))
    return list(pending.values())[-1] if pending else None


def _codex_pending(path: Path) -> Optional[tuple]:
    pending: dict = {}
    for entry in _jsonl(path):
        payload = entry.get("payload")
        if entry.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind in ("function_call", "custom_tool_call", "local_shell_call"):
            pending[payload.get("call_id")] = (payload.get("name") or "shell", payload.get("arguments") or payload.get("input"))
        elif kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            pending.pop(payload.get("call_id"), None)
    return list(pending.values())[-1] if pending else None


def _opencode_pending(session_id: str, home: Path = HOME) -> Optional[tuple]:
    """A tool whose state isn't finished: opencode updates the row in place when it completes."""
    def unfinished(block) -> Optional[tuple]:
        state = block.get("state") if isinstance(block, dict) else None
        if isinstance(state, dict) and block.get("type") == "tool" and state.get("status") not in ("completed", "error"):
            return block.get("name") or block.get("tool"), state.get("input")
        return None

    queries = [("SELECT data FROM session_message WHERE session_id = ? AND type = 'assistant' ORDER BY seq DESC LIMIT 3",
                lambda message: message.get("content")),
               ("SELECT data FROM part WHERE session_id = ? ORDER BY time_created DESC, id DESC LIMIT 20",
                lambda part: [part])]
    for path in opencode_databases(home):
        try:
            db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            continue
        try:
            for query, blocks in queries:
                try:
                    rows = db.execute(query, (session_id,)).fetchall()
                except sqlite3.OperationalError:
                    continue
                for (data,) in rows:
                    record = _json(data)
                    for block in reversed((blocks(record) or []) if record else []):
                        found = unfinished(block)
                        if found:
                            return found
        except sqlite3.Error:
            continue
        finally:
            db.close()
    return None


def _basename(value) -> str:
    return Path(str(value)).name if value else "a file"


def _program(command) -> str:
    """The program a shell command runs: 'npm' for 'cd app && FOO=1 npm test'; '' when unclear."""
    command = " ".join(command) if isinstance(command, list) else str(command)
    embedded = re.search(r"\bcmd\s*:\s*[\"'`]([^\"'`]+)", command)  # Codex code mode: exec_command({cmd: "…"})
    if embedded:
        command = embedded.group(1)
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        words = [w for w in segment.split() if not re.fullmatch(r"\w+=\S*", w)]
        while words and words[0] in ("sudo", "env", "time", "nohup", "exec"):
            words = words[1:]
        if not words or words[0] in ("cd", "export", "set", "source", "."):
            continue
        program = Path(words[0]).name
        return program if re.fullmatch(r"[A-Za-z][\w.+-]{0,29}", program) else ""
    return ""


def describe_request(name, arguments) -> str:
    """'wants to run git', 'asks: …': what a pending tool call asks the user to approve or answer."""
    tool = str(name or "").lower()
    args = _arguments(arguments)
    if tool in QUESTION_TOOLS:
        questions = args.get("questions") if isinstance(args.get("questions"), list) else [args]
        spoken = []
        for question in questions[:3]:
            if not isinstance(question, dict):
                continue
            text = str(question.get("question") or question.get("prompt") or "").strip()
            options = [str(o.get("label") if isinstance(o, dict) else o) for o in question.get("options") or []][:6]
            if text:
                spoken.append(text + (f" Options: {', '.join(options)}." if options else ""))
        return "asks: " + " ".join(spoken) if spoken else "has a question for you"
    if tool == "exitplanmode":
        return "has a plan ready for you to review"
    if tool in SHELL_TOOLS:
        description = args.get("description") or args.get("justification")
        if isinstance(description, str) and description.strip():
            text = description.strip()
            if len(text) > 1 and text[1].islower():  # "Push the branch" -> "push the branch"; keep "API …"
                text = text[0].lower() + text[1:]
            return f"wants to run a command: {text}"
        source = args.get("command") or args.get("cmd") or args.get("input") or ""
        if tool == "exec" and not re.search(r"\bcmd\s*:", str(source)):
            return "wants to run code"  # Codex code mode: JavaScript, not a shell command
        program = _program(source)
        return f"wants to run {program}" if program else "wants to run a command"
    path = args.get("file_path") or args.get("path") or args.get("filePath") or args.get("notebook_path")
    if tool in EDIT_TOOLS:
        return f"wants to {'write' if tool == 'write' else 'edit'} {_basename(path)}"
    if tool == "read":
        return f"wants to read {_basename(path)}"
    if tool in ("webfetch", "web_fetch", "fetch") and args.get("url"):
        host = re.sub(r"^\w+://", "", str(args["url"])).split("/")[0]
        return f"wants to fetch from {host}"
    readable = re.sub(r"[_-]+", " ", re.sub(r"^mcp__", "", str(name or "a tool"))).strip()
    return f"wants to use {readable}"


def pending_request(agent: dict) -> Optional[str]:
    """What a blocked agent is asking for, from its newest tool call that has no result yet."""
    kind = agent.get("agent")
    value = (agent.get("agent_session") or {}).get("value")
    call = None
    try:
        if kind == "claude" and value:
            path = claude_transcript(value)
            call = _claude_pending(path) if path else None
        elif kind == "pi" and value:
            call = _pi_pending(Path(value))
        elif kind == "codex":
            path = codex_transcript(value, agent.get("foreground_cwd") or agent.get("cwd"))
            call = _codex_pending(path) if path else None
        elif kind == "opencode" and value:
            call = _opencode_pending(value)
    except OSError:
        return None
    return describe_request(*call) if call else None


def last_response(agent: dict) -> Optional[str]:
    """The last response of the agent described by `herdr agent get`."""
    return _last(responses(agent))
