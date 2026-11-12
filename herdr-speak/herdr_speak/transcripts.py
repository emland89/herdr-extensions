"""Find an agent's last response in its own session transcript.

Reading transcripts instead of the screen gets the full response, including
parts scrolled out of view, without terminal decoration. Transcript content is
untrusted data: it is only ever spoken, never executed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

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


def last_pi_message(path: Path) -> Optional[str]:
    last = None
    for entry in _jsonl(path):
        message = entry.get("message")
        if entry.get("type") == "message" and isinstance(message, dict) and message.get("role") == "assistant":
            text = _text_blocks(message.get("content"))
            if text.strip():
                last = text
    return last


def last_claude_message(path: Path) -> Optional[str]:
    # One API message is stored as several entries (one per content block)
    # sharing message.id; join the text blocks of the last one that has text.
    last_id, chunks = None, []
    for entry in _jsonl(path):
        message = entry.get("message")
        if entry.get("type") != "assistant" or entry.get("isSidechain") or not isinstance(message, dict):
            continue
        text = _text_blocks(message.get("content"))
        if not text.strip():
            continue
        message_id = message.get("id")
        if message_id != last_id:
            last_id, chunks = message_id, []
        chunks.append(text)
    return "\n\n".join(chunks) or None


def last_codex_message(path: Path) -> Optional[str]:
    last = None
    for entry in _jsonl(path):
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "event_msg" and payload.get("type") == "task_complete":
            text = payload.get("last_agent_message")
            text = text if isinstance(text, str) else ""
        elif entry.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            text = _text_blocks(payload.get("content"))
        else:
            continue
        if text.strip():
            last = text
    return last


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


SUPPORTED_AGENTS = {"pi": "Pi", "claude": "Claude", "codex": "Codex"}


def last_response(agent: dict) -> Optional[str]:
    """The last response of the agent described by `herdr agent get`."""
    kind = agent.get("agent")
    value = (agent.get("agent_session") or {}).get("value")
    if kind == "pi" and value:
        return last_pi_message(Path(value))
    if kind == "claude" and value:
        path = claude_transcript(value)
        return last_claude_message(path) if path else None
    if kind == "codex":
        path = codex_transcript(value, agent.get("foreground_cwd") or agent.get("cwd"))
        return last_codex_message(path) if path else None
    if kind in SUPPORTED_AGENTS:
        raise RuntimeError(f"Herdr hasn't reported a session for {SUPPORTED_AGENTS[kind]} in this pane yet")
    raise RuntimeError(f"Reading responses from {kind or 'this pane'} isn't supported")
