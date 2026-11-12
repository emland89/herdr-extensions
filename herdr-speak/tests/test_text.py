import time
import unittest

from herdr_speak.text import clean_for_speech, paragraphs, plain_label, split_long_lines
from tests.support import ROOT  # noqa: F401  (puts the plugin on sys.path)


class CleanForSpeechTest(unittest.TestCase):
    def test_skips_code_and_tables(self):
        text = clean_for_speech("Intro\n\n```py\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\nAfter")
        self.assertEqual(text, "Intro.\n\nCode block skipped.\n\nTable skipped.\n\nAfter.")

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


if __name__ == "__main__":
    unittest.main()
