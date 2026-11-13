import time
import unittest

from herdr_speak.text import FIRST_PIECE, MIN_TAIL, clean_for_speech, paragraphs, plain_label, speech_pieces, split_long_lines
from tests.support import ROOT  # noqa: F401  (puts the plugin on sys.path)


class CleanForSpeechTest(unittest.TestCase):
    def test_skips_code_and_reads_small_tables(self):
        text = clean_for_speech("Intro\n\n```py\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\nAfter")
        self.assertEqual(text, "Intro.\n\nCode block skipped.\n\nTable, 1 row. Columns: a, b.\n\na: 1; b: 2.\n\n"
                               "End of table.\n\nAfter.")

    def test_lines_with_pipes_but_no_delimiter_row_are_skipped(self):
        self.assertEqual(clean_for_speech("| just | pipes |\n| more |\nAfter"), "Table skipped.\n\nAfter.")

    def test_strips_markdown(self):
        text = clean_for_speech("## Title\n- **Bold** and _it_ [docs](https://x.y)\n> quote at https://a.b/c\n1. First")
        self.assertEqual(text, "Title.\n\nBold and it docs.\n\nquote at link.\n\nFirst.")

    def test_long_inline_path_becomes_name(self):
        self.assertEqual(clean_for_speech("See `/Users/me/project/src/index.ts`."), "See index.ts.")
        self.assertEqual(clean_for_speech("Run `npm test`."), "Run npm test.")

    def test_keeps_snake_case_and_multiplication(self):
        self.assertEqual(clean_for_speech("Set copy_on_select to 2 * 3!"), "Set copy_on_select to 2 * 3!")

    def test_localizes_skipped_content(self):
        text = clean_for_speech("Hola\n\n```\nx\n```\nVer https://x.y", "es")
        self.assertEqual(text, "Hola.\n\nBloque de código omitido.\n\nVer enlace.")

    def test_nested_fences_and_angle_brackets(self):
        self.assertEqual(clean_for_speech("Intro\n````md\n```py\ncode\n```\n````\nAfter"),
                         "Intro.\n\nCode block skipped.\n\nAfter.")
        self.assertEqual(clean_for_speech("Use Vec<String> when a<b and c>d.<br/>"), "Use Vec<String> when a<b and c>d.")
        self.assertEqual(clean_for_speech('<a href="x">docs</a> <strong>now</strong>'), "docs now.")

    def test_long_lines_with_many_markers_stay_fast(self):
        start = time.time()
        for text in (" _b" * 7000, " *y" * 7000, "**x" * 7000, "__" * 10000):
            clean_for_speech(text)
        self.assertLess(time.time() - start, 1.0)

    def test_hostile_input_stays_fast(self):
        start = time.time()
        for text in ("<a x=1" * 20000, "![" * 20000, "[" * 50000 + "](", "[x](" * 20000, "x" * 500_000):
            clean_for_speech(text)
        self.assertLess(time.time() - start, 2.0)

    def test_say_commands_are_defused(self):
        self.assertNotIn("[[", clean_for_speech("Hi. [[slnc 30000]] bye [[volm 1]]."))
        self.assertNotIn("]]", clean_for_speech("[[inpt PHON]]x"))

    def test_plain_label_strips_control_sequences(self):
        self.assertEqual(plain_label("Claude in \x1b]52;c;eA==\x07api\x1b[2J"), "Claude in ]52;c;eA==api[2J")
        self.assertEqual(len(plain_label("x" * 500)), 80)

    def test_unclosed_fence_is_skipped_to_the_end(self):
        self.assertEqual(clean_for_speech("Before\n```\nnever closed"), "Before.\n\nCode block skipped.")


STATUS = """| File | Change | Tests |
|---|---|:-:|
| `src/auth.py` | added **token refresh** | ✅ |
| `src/db.py` | — | ❌ |
| README.md | docs<br>and examples | ⚠️ |"""


def table(rows: int, columns: int = 2) -> str:
    header = "| " + " | ".join(f"C{c}" for c in range(columns)) + " |"
    body = ["| " + " | ".join(f"r{r}c{c}" for c in range(columns)) + " |" for r in range(rows)]
    return "\n".join([header, "|" + "---|" * columns, *body])


class TableTest(unittest.TestCase):
    def paragraphs(self, markdown, mode="auto"):
        return paragraphs(clean_for_speech(markdown, "en-us", mode))

    def test_small_table_is_read_row_by_row_with_headers(self):
        self.assertEqual(self.paragraphs(STATUS), [
            "Table, 3 rows. Columns: File, Change, Tests.",
            "src/auth.py: Change: added token refresh; Tests: yes.",
            "src/db.py: Tests: no.",  # the empty "—" cell is left out
            "README.md: Change: docs, and examples; Tests: warning.",
        ])

    def test_big_table_reads_three_rows_then_counts_the_rest(self):
        spoken = self.paragraphs(table(10))
        self.assertEqual(spoken[0], "Table, 10 rows. Columns: C0, C1.")
        self.assertEqual(spoken[1:4], ["r0c0: C1: r0c1.", "r1c0: C1: r1c1.", "r2c0: C1: r2c1."])
        self.assertEqual(spoken[-1], "And 7 more rows.")

    def test_wide_tables_get_the_announcement_only(self):
        self.assertEqual(self.paragraphs(table(2, 9)), ["Table, 2 rows, 9 columns, starting with C0, C1, C2."])
        self.assertEqual(self.paragraphs(table(2, 6))[0], "Table, 2 rows, 6 columns, starting with C0, C1, C2.")

    def test_modes(self):
        self.assertEqual(self.paragraphs(STATUS, "skip"), ["Table with 3 rows, skipped."])
        self.assertEqual(self.paragraphs(STATUS, "summary"), ["Table, 3 rows. Columns: File, Change, Tests."])
        self.assertEqual(len(self.paragraphs(table(10), "rows")), 11)  # every row
        self.assertEqual(self.paragraphs(STATUS, "nonsense"), self.paragraphs(STATUS))  # unknown: auto

    def test_tables_without_outer_pipes_and_with_escaped_pipes(self):
        self.assertEqual(self.paragraphs("Name | Value\n--- | ---\napi | a \\| b"),
                         ["Table, 1 row. Columns: Name, Value.", "api: Value: a | b."])

    def test_numeric_first_column_is_not_a_label_and_headerless_rows_are_plain(self):
        self.assertEqual(self.paragraphs("| # | Step |\n|---|---|\n| 1 | build |")[1], "#: 1; Step: build.")
        self.assertEqual(self.paragraphs("| | |\n|---|---|\n| a | b |"), ["Table, 1 row.", "a, b."])

    def test_symbols_are_spoken_in_prose_too(self):
        spoken = clean_for_speech("✅ Done in ~12 ms, from 40ms → 25ms (±3%). Δ: N/A. Tests: ❌")
        self.assertEqual(spoken, "Done in about 12 milliseconds, from 40 milliseconds to 25 milliseconds "
                                 "(plus or minus 3%). change: not applicable. Tests: no.")

    def test_other_languages_announce_in_their_own_words(self):
        self.assertEqual(paragraphs(clean_for_speech(STATUS, "es"))[0], "Tabla, 3 filas. Columnas: File, Change, Tests.")


class SplitTest(unittest.TestCase):
    def test_splits_long_lines_at_sentences_then_clauses(self):
        sentence = "word " * 30 + "end."
        lines = split_long_lines(" ".join([sentence] * 4), limit=200).split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line) <= 200 for line in lines))
        clause = ", ".join(["a b c d e f g"] * 40) + "."
        self.assertTrue(all(len(line) <= 100 for line in split_long_lines(clause, limit=100).split("\n")))

    def test_paragraphs(self):
        self.assertEqual(paragraphs("a\n\n\n b \n\n"), ["a", "b"])

    def test_speech_starts_with_a_short_piece_cut_at_a_natural_break(self):
        text = ("The tests pass now, and the build is green; I also cleaned up the old fixtures that "
                "were no longer used by anything.\n\nSecond paragraph.")
        pieces = speech_pieces(text)
        self.assertLessEqual(len(pieces[0][0]), FIRST_PIECE * 3 // 2)
        self.assertEqual(pieces[0], ("The tests pass now, and the build is green;", False))
        self.assertEqual(" ".join(piece for piece, _ in pieces[:-1]), paragraphs(text)[0])  # nothing lost or reordered
        self.assertEqual([end for _, end in pieces][-1], True)
        self.assertTrue(all(len(piece) >= MIN_TAIL or end for piece, end in pieces))

    def test_later_paragraphs_stay_whole(self):
        long = "This sentence keeps going for quite a while, as agent replies do. " * 3
        pieces = speech_pieces("\n\n".join([long.strip()] * 6))
        self.assertEqual(sum(end for _, end in pieces), 6)
        self.assertEqual([end for _, end in pieces][-3:], [True, True, True])  # splitting stopped


if __name__ == "__main__":
    unittest.main()
