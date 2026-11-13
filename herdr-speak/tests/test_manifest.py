"""The manifest declares what the code implements, and the marketplace can parse it."""

import re
import unittest

from tests.support import ROOT

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

COMMANDS = {"last", "selection", "stop", "toggle-pause", "forward", "back", "skip", "previous", "next", "toggle-auto", "event",
            "panel", "open-panel", "mini", "mini-player", "follow", "setup"}
ID = re.compile(r"^[A-Za-z0-9:_-]+$")  # Herdr's local id rule: no dots


@unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
class ManifestTest(unittest.TestCase):
    def setUp(self):
        with open(ROOT / "herdr-plugin.toml", "rb") as handle:
            self.manifest = tomllib.load(handle)

    def test_required_metadata(self):
        for key in ("id", "name", "version", "min_herdr_version"):
            self.assertTrue(self.manifest.get(key), key)
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_version_matches_package(self):
        from herdr_speak import __version__

        self.assertEqual(self.manifest["version"], __version__)

    def test_every_entrypoint_runs_a_known_command(self):
        entries = self.manifest.get("actions", []) + self.manifest.get("events", []) + \
            self.manifest.get("panes", []) + self.manifest.get("build", [])
        for entry in entries:
            command = entry["command"]
            self.assertEqual(command[:2], ["python3", "speak.py"], entry)
            self.assertIn(command[2], COMMANDS, entry)

    def test_local_ids_are_valid_and_unique(self):
        for kind in ("actions", "panes"):
            ids = [entry["id"] for entry in self.manifest.get(kind, [])]
            self.assertEqual(len(ids), len(set(ids)), kind)
            for local_id in ids:
                self.assertRegex(local_id, ID)

    def test_panel_action_opens_the_declared_pane(self):
        from herdr_speak import herdr  # noqa: F401  (open_panel uses the "panel" entrypoint)

        self.assertIn("panel", [pane["id"] for pane in self.manifest["panes"]])

    def test_events_are_known(self):
        self.assertEqual({event["on"] for event in self.manifest["events"]},
                         {"pane.agent_status_changed", "tab.focused", "workspace.focused"})


if __name__ == "__main__":
    unittest.main()
