"""Where the mini player lives: open, bring here, close, and follow mode (Herdr calls mocked)."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from herdr_speak import mini, paths
from tests.support import isolate

PANES = [
    {"pane_id": "w1:p1", "tab_id": "w1:t1", "focused": False},
    {"pane_id": "w1:p9", "tab_id": "w1:t1", "focused": False},  # the mini player
    {"pane_id": "w2:p3", "tab_id": "w2:t1", "focused": True},
]


class FakeHerdr:
    def __init__(self, panes):
        self.panes = panes
        self.calls = []

    def run_json(self, *args):
        self.calls.append(args)
        if args[:2] == ("pane", "list"):
            return {"panes": self.panes}
        if args[:2] == ("pane", "move"):
            return {"move_result": {"pane": {"pane_id": "w2:p7"}}}
        if args[:3] == ("plugin", "pane", "open"):
            return {"plugin_pane": {"pane": {"pane_id": "w2:p8"}}}
        return {}


class MiniLocationTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        self.herdr = FakeHerdr(PANES)
        for name in ("run_json", "invocation_context", "resize_to_rows"):
            replacement = {"run_json": self.herdr.run_json, "invocation_context": lambda: {},
                           "resize_to_rows": lambda *a: None}[name]
            patch = mock.patch(f"herdr_speak.herdr.{name}", side_effect=replacement)
            patch.start()
            self.addCleanup(patch.stop)
        # A live process whose command line looks like the mini player.
        self.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "speak.py mini"])
        self.addCleanup(lambda: (self.process.kill(), self.process.wait()))

    def running_mini(self, tab="w1:t1"):
        mini.write_state("w1:p9", tab, self.process.pid)

    def commands(self):
        return [call[:2] for call in self.herdr.calls if call[:2] != ("pane", "list")]

    def test_live_mini_requires_a_running_mini_process(self):
        self.assertIsNone(mini.live_mini())
        mini.write_state("w1:p9", "w1:t1", os.getpid())  # alive, but not a mini player
        self.assertIsNone(mini.live_mini())
        self.running_mini()
        self.assertEqual(mini.live_mini()["pane"], "w1:p9")

    def test_toggle_opens_below_the_focused_pane(self):
        mini.toggle()
        opened = next(call for call in self.herdr.calls if call[:3] == ("plugin", "pane", "open"))
        self.assertIn("w2:p3", opened)  # --target-pane: the focused pane

    def test_toggle_brings_it_from_another_tab(self):
        self.running_mini(tab="w1:t1")
        mini.toggle()
        move = next(call for call in self.herdr.calls if call[:2] == ("pane", "move"))
        self.assertEqual(move[2], "w1:p9")
        self.assertIn("w2:t1", move)
        self.assertIn("--no-focus", move)
        self.assertEqual(json.loads((paths.STATE_DIR / "mini.json").read_text())["pane"], "w2:p7")

    def test_toggle_closes_it_when_it_is_here(self):
        self.running_mini(tab="w2:t1")
        mini.toggle()
        self.assertEqual(self.commands(), [("pane", "close")])

    def test_follow_is_off_by_default(self):
        self.running_mini()
        mini.follow({"mini_follow": False})
        self.assertEqual(self.commands(), [])

    def test_follow_moves_it_to_the_tab_in_view(self):
        self.running_mini(tab="w1:t1")
        mini.follow({"mini_follow": True})
        self.assertEqual(self.commands(), [("pane", "move")])

    def test_follow_does_nothing_in_the_same_tab_or_when_the_mini_has_focus(self):
        self.running_mini(tab="w2:t1")
        mini.follow({"mini_follow": True})
        self.herdr.panes = [dict(p, focused=p["pane_id"] == "w1:p9") for p in PANES]
        self.running_mini(tab="w1:t1")
        mini.follow({"mini_follow": True})
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()
