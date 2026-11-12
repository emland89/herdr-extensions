"""Turn agent markdown into text that sounds natural when spoken."""

from __future__ import annotations

import re

from . import catalog

# A fence closes only with a run of the same character at least as long as the opening one.
_FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n?.*?(?:^[ \t]*(?P=fence)[`~]*[ \t]*$|\Z)", re.S | re.M)
# Bounded repeats keep every pattern linear on hostile input (an agent can be made to write anything).
_LINK = re.compile(r"!?\[([^\[\]\n]{0,300})\]\([^()\s]{0,2000}\)")
_URL = re.compile(r"https?://\S+")
_INLINE_CODE = re.compile(r"`([^`]+)`")
# Each emphasis pattern stops at the next marker character, so matching stays linear on long lines.
_EMPHASIS = [
    re.compile(r"\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*"),
    re.compile(r"__(?=\S)([^_\n]+?)(?<=\S)__"),
    re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])"),
    re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])"),
]
# Only HTML tags agents actually write, so "Vec<String>" and "a<b and c>d" survive.
_TAG = re.compile(
    r"</?(?:a|b|br|code|details|div|em|hr|i|img|kbd|li|ol|p|pre|span|strong|sub|summary|sup|table|td|th|tr|u|ul)"
    r"(?:\s+[\w:-]{1,40}=(?:\"[^\"<>\n]{0,500}\"|'[^'<>\n]{0,500}'|[^\s<>\"']{1,200})){0,20}\s*/?>",
    re.I,
)
CODE_MARKER = "\x00code\x00"
MAX_INPUT = 100_000  # characters; longer responses are cut (about two hours of speech)
_SAY_COMMAND = re.compile(r"\[\[|\]\]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def defuse_say(text: str) -> str:
    """macOS `say` obeys embedded commands such as [[slnc 30000]] or [[volm 1]]; break them up."""
    return _SAY_COMMAND.sub(lambda m: m.group()[0] + " " + m.group()[1], text)


def plain_label(text: str, limit: int = 80) -> str:
    """A title safe to draw in a terminal: no escape or control characters."""
    return _CONTROL.sub("", str(text))[:limit]


def _inline_code(match: re.Match) -> str:
    code = match.group(1)
    # Long paths read badly; keep the file or folder name.
    if "/" in code and " " not in code and len(code) > 20:
        return code.rstrip("/").rsplit("/", 1)[-1] or code
    return code


def split_long_lines(text: str, limit: int = 350) -> str:
    """Break lines over `limit` characters at sentence, then clause, boundaries.

    Kokoro handles at most 510 phonemes per call; shorter chunks also start sooner.
    """
    out = []
    for line in text.split("\n"):
        if len(line) <= limit:
            out.append(line)
            continue
        pieces = re.split(r"(?<=[.!?。])\s+", line)
        pieces = [part for piece in pieces for part in
                  (re.split(r"(?<=[,;:])\s+", piece) if len(piece) > limit else [piece])]
        chunk = ""
        for piece in pieces:
            if chunk and len(chunk) + 1 + len(piece) > limit:
                out.append(chunk)
                chunk = piece
            else:
                chunk = f"{chunk} {piece}" if chunk else piece
        out.append(chunk)
    return "\n".join(out)


def clean_for_speech(markdown: str, language: str = catalog.DEFAULT_LANGUAGE) -> str:
    """Markdown in, one spoken paragraph per blank-line-separated block out."""
    words = catalog.language(language)
    text = defuse_say(markdown[:MAX_INPUT])
    text = _FENCE.sub(f"\n\n{CODE_MARKER}\n\n", text)
    lines, in_table = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line == CODE_MARKER:
            lines.append(words["code"])
            in_table = False
            continue
        if line.startswith("|"):
            if not in_table:
                lines.append(words["table"])
            in_table = True
            continue
        in_table = False
        if re.fullmatch(r"[-*_]{3,}", line):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s?", "", line)
        line = re.sub(r"^([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", line)
        line = _LINK.sub(r"\1", line)
        line = _URL.sub(words["link"], line)
        line = _INLINE_CODE.sub(_inline_code, line)
        for pattern in _EMPHASIS:
            line = pattern.sub(r"\1", line)
        line = re.sub(r"[ \t]{2,}", " ", _TAG.sub("", line)).strip()
        # A pause after headings and list items, which usually lack punctuation.
        if line and line[-1].isalnum():
            line += "."
        lines.append(line)
    spoken = split_long_lines("\n".join(lines))
    return "\n\n".join(line for line in spoken.split("\n") if line.strip())


def paragraphs(text: str) -> list:
    return [part.strip() for part in text.split("\n\n") if part.strip()]
