"""Turn agent markdown into text that sounds natural when spoken."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

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


# ---------------------------------------------------------------- tables and symbols
#
# Tables follow docs/research/reading-tables.md: announce the size and columns, then one
# paragraph per row with each value after its column header ("auth.py: Change: added
# refresh; Tests: yes."), as screen readers and the HTML spec's speech example do. Big
# tables are summarized: listeners keep only a handful of spoken items.

TABLE_MODES = ["auto", "rows", "summary", "skip"]
TABLE_MODE_LABELS = {"auto": "Auto: summarize big ones", "rows": "Every row",  # fit the panel's dropdown
                     "summary": "Size and columns only", "skip": "Skip, say the size"}
FULL_ROWS, FULL_COLUMNS = 6, 5  # auto reads tables up to this size in full
PREVIEW_ROWS = 3  # rows auto reads from a bigger table
MAX_COLUMNS = 8  # wider tables get the announcement only (auto)
NAMED_COLUMNS = 5  # up to this many column names are listed in the announcement

_DELIMITER = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")
_EMPTY_CELL = re.compile(r"^[-–—]?$")
_NUMBERISH = re.compile(r"^[\d\s.,:%#+-]+$")
_YES, _NO, _WARNING = "(?:✅|✓|✔|☑)\ufe0f?", "(?:❌|✗|✘|✖)\ufe0f?", "⚠\ufe0f?"


def speak_symbols(line: str, words: dict) -> str:
    """Symbols the voice can't say (Misaki drops them): status marks, arrows, units."""
    for symbol, word in ((_YES, words["yes"]), (_NO, words["no"]), (_WARNING, words["warning"])):
        line = re.sub(symbol + r"\s*(?=[^\W\d_])", "", line)  # "✅ done": the word says it
        line = re.sub(symbol, f" {word} ", line)
    line = re.sub(r"\b[Nn]/[Aa]\b", words["not_applicable"], line)
    line = re.sub(r"(\d)\s?ms\b", rf"\1 {words['milliseconds']}", line)
    line = re.sub(r"~\s?(?=\d)", f"{words['about']} ", line)
    line = line.replace("±", f" {words['plus_minus']} ").replace("→", f" {words['to']} ").replace("Δ", f" {words['change']} ")
    # Tidy the spaces the words brought, but never join "[ [": defuse_say split those on purpose.
    line = re.sub(r"\(\s+", "(", line)  # "( plus" -> "(plus"
    line = re.sub(r"\s+([:;,.!?)])", r"\1", line)  # "change :" -> "change:"
    return re.sub(r"[ \t]{2,}", " ", line).strip()


def _inline(line: str, words: dict) -> str:
    """Markdown inside a line: links, code spans, emphasis, tags, and symbols."""
    line = _LINK.sub(r"\1", line)
    line = _URL.sub(words["link"], line)
    line = _INLINE_CODE.sub(_inline_code, line)
    for pattern in _EMPHASIS:
        line = pattern.sub(r"\1", line)
    line = speak_symbols(_TAG.sub(" ", line), words)
    return re.sub(r"[ \t]{2,}", " ", line).strip()


def table_cells(line: str) -> List[str]:
    """A row's cells, split at pipes that aren't escaped (GFM allows \\| inside a cell)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def _is_table_start(lines: List[str], index: int) -> bool:
    """A header line with pipes followed by a delimiter row (|---|:--:|), as GFM defines a table."""
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    delimiter = lines[index + 1].strip()
    return "-" in delimiter and ("|" in delimiter or "|" in lines[index]) and bool(_DELIMITER.match(delimiter))


def _count(count: int, words: dict) -> str:
    return f"{count} {words['row'] if count == 1 else words['rows']}"


def _cell(text: str, words: dict) -> str:
    text = re.sub(r"\s*<br\s*/?>\s*", ", ", text, flags=re.I)  # a line break inside a cell
    text = _inline(text, words).strip(" .;,")
    return "" if _EMPTY_CELL.match(text) else text


def speak_row(header: List[str], cells: List[str]) -> str:
    """'auth.py: Change: added refresh; Tests: yes.' with the first cell as the row's label."""
    cells = (cells + [""] * len(header))[: len(header)]  # GFM: missing cells are empty, extra ones dropped
    if not any(header):
        return ", ".join(cell for cell in cells if cell) + "."
    labelled = bool(cells[0]) and not _NUMBERISH.match(cells[0])
    pairs = [f"{name}: {cell}" if name else cell
             for name, cell in zip(header[1:] if labelled else header, cells[1:] if labelled else cells) if cell]
    if labelled:
        return f"{cells[0]}: {'; '.join(pairs)}." if pairs else f"{cells[0]}."
    return "; ".join(pairs) + "." if pairs else ""


def speak_table(header: List[str], rows: List[List[str]], words: dict, mode: str = "auto",
                more_follows: bool = False) -> List[str]:
    """The spoken lines for one table: an announcement, then rows as the mode says."""
    header = [_cell(cell, words) for cell in header]
    rows = [[_cell(cell, words) for cell in row] for row in rows]
    rows = [row for row in rows if any(row)]
    size = _count(len(rows), words)
    if mode == "skip":
        return [words["table_skipped"].format(size=size)]
    named = [name for name in header if name]
    if not named:
        intro = words["table_intro_plain"].format(size=size)
    elif len(named) <= NAMED_COLUMNS:
        intro = words["table_intro"].format(size=size, columns=", ".join(named))
    else:
        intro = words["table_intro_wide"].format(size=size, count=len(header), columns=", ".join(named[:3]))
    if mode == "summary" or (mode == "auto" and len(header) > MAX_COLUMNS) or not rows:
        return [intro]
    full = mode == "rows" or (len(rows) <= FULL_ROWS and len(header) <= FULL_COLUMNS)
    shown = rows if full else rows[:PREVIEW_ROWS]
    spoken = [intro] + [line for line in (speak_row(header, row) for row in shown) if line]
    rest = len(rows) - len(shown)
    if rest:
        spoken.append(words["table_more"].format(count=rest, rows=words["row"] if rest == 1 else words["rows"]))
    elif more_follows:
        spoken.append(words["table_end"])
    return spoken


def clean_for_speech(markdown: str, language: str = catalog.DEFAULT_LANGUAGE, tables: str = "auto") -> str:
    """Markdown in, one spoken paragraph per blank-line-separated block out.

    `tables`: "auto", "rows", "summary", or "skip" (see speak_table).
    """
    words = catalog.language(language)
    text = defuse_say(markdown[:MAX_INPUT])
    text = _FENCE.sub(f"\n\n{CODE_MARKER}\n\n", text)
    source = [raw.strip() for raw in text.splitlines()]
    lines, in_stray_table, index = [], False, 0
    while index < len(source):
        line = source[index]
        index += 1
        if line == CODE_MARKER:
            lines.append(words["code"])
            in_stray_table = False
            continue
        if _is_table_start(source, index - 1):
            header, rows = table_cells(line), []
            index += 1  # the delimiter row
            while index < len(source) and source[index] and "|" in source[index]:
                rows.append(table_cells(source[index]))
                index += 1
            follows = any(rest and rest != CODE_MARKER for rest in source[index:])
            lines += speak_table(header, rows, words, tables if tables in TABLE_MODES else "auto", follows)
            continue
        if line.startswith("|"):  # pipes without a delimiter row: not a table we can read
            if not in_stray_table:
                lines.append(words["table"])
            in_stray_table = True
            continue
        in_stray_table = False
        if re.fullmatch(r"[-*_]{3,}", line):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s?", "", line)
        line = re.sub(r"^([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", line)
        line = _inline(line, words)
        # A pause after headings and list items, which usually lack punctuation.
        if line and line[-1].isalnum():
            line += "."
        lines.append(line)
    spoken = split_long_lines("\n".join(lines))
    return "\n\n".join(line for line in spoken.split("\n") if line.strip())


def paragraphs(text: str) -> list:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


# Speech starts once the first piece is synthesized, so the first piece is short (about
# 3 s of speech, ready in under a second), and each later piece is at most twice as long
# as everything before it: synthesis runs about four times faster than speech, so the next
# piece is ready before the audio runs out. Once STOP_SPLITTING characters are queued,
# whole paragraphs go.
FIRST_PIECE = 30
STOP_SPLITTING = 400
MIN_TAIL = 25  # never leave a fragment shorter than this
_SENTENCE_END = re.compile(r"[.!?…:;](?=\s)")
_CLAUSE_END = re.compile(r"(?:,|\s[—–-])(?=\s)")


def _cut(text: str, limit: int) -> Optional[int]:
    """Where to end a piece of about `limit` characters: a sentence end, else a clause end
    (either may run up to half again past the limit), else the last word that fits."""
    floor, stretch = min(20, limit // 2), limit + limit // 2
    for pattern in (_SENTENCE_END, _CLAUSE_END):
        ends = [m.end() for m in pattern.finditer(text, 0, stretch + 1)
                if floor <= m.end() and len(text) - m.end() >= MIN_TAIL]
        if ends:
            within = [end for end in ends if end <= limit]
            return within[-1] if within else ends[0]
    space = text.rfind(" ", floor, limit + 1)
    return space if space > 0 and len(text) - space >= MIN_TAIL else None


def speech_pieces(text: str) -> List[Tuple[str, bool]]:
    """(piece, ends a paragraph) in reading order: paragraphs, the first ones split so speech starts fast."""
    pieces: List[Tuple[str, bool]] = []
    queued = 0
    for paragraph in paragraphs(text):
        rest = paragraph
        while queued < STOP_SPLITTING:
            limit = max(FIRST_PIECE, 2 * queued)
            if len(rest) <= limit:
                break
            cut = _cut(rest, limit)
            if cut is None:
                break
            piece, rest = rest[:cut].strip(), rest[cut:].strip()
            pieces.append((piece, False))
            queued += len(piece)
        pieces.append((rest, True))
        queued += len(rest)
    return pieces
