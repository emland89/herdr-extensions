"""Adding and removing Speak's key bindings in Herdr's config.toml (Herdr's reload mocked)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from herdr_speak import bindings

try:
    import tomllib
except ImportError:  # Python < 3.11: the TOML validity checks are skipped
    tomllib = None

EXISTING = """onboarding = false
[ui]
agent_panel_sort = "priority"
[ui.toast]
delivery = "system"

[theme]
name = "dracula"
"""


class BindingsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.toml"
        patch = mock.patch.object(bindings, "reload_herdr", return_value=[])
        self.reload = patch.start()
        self.addCleanup(patch.stop)

    def parse(self):
        if tomllib is not None:
            return tomllib.loads(self.path.read_text())
        return None

    def speak_keys(self):
        config = self.parse()
        if config is None:
            return None
        return {c["key"]: c["command"] for c in config.get("keys", {}).get("command", [])}

    def test_fresh_config_gets_every_binding_and_the_indicator(self):
        result = bindings.bind(self.path)
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["added"]), len(bindings.DEFAULT_BINDINGS))
        config = self.parse()
        if config is not None:
            self.assertEqual(self.speak_keys()["prefix+t"], "emilapps.speak.read-last")
            self.assertIn("statusline", config["ui"]["tab_bar_right"][0]["command"])

    def test_existing_ui_table_gets_the_indicator_inside_it(self):
        self.path.write_text(EXISTING)
        bindings.bind(self.path)
        text = self.path.read_text()
        self.assertEqual(text.count("[ui]\n"), 1)  # TOML can't define [ui] twice
        config = self.parse()
        if config is not None:
            self.assertEqual(config["ui"]["agent_panel_sort"], "priority")
            self.assertEqual(config["ui"]["toast"]["delivery"], "system")
            self.assertEqual(len(config["ui"]["tab_bar_right"]), 1)

    def test_taken_keys_and_own_bindings_are_left_alone(self):
        self.path.write_text(EXISTING + '''
[[keys.command]]
key = "prefix+t"
type = "shell"
command = "my-tool"

[[keys.command]]
key = "prefix+y"
type = "plugin_action"
command = "emilapps.speak.panel"
''')
        result = bindings.bind(self.path)
        self.assertNotIn("prefix+t", result["added"])  # used by the user's own tool
        self.assertNotIn("prefix+shift+a", result["added"])  # the panel is already bound (prefix+y)
        self.assertTrue(any("prefix+t" in note for note in result["notes"]))

    def test_running_twice_changes_nothing_and_unbind_restores(self):
        self.path.write_text(EXISTING)
        bindings.bind(self.path)
        once = self.path.read_text()
        self.assertFalse(bindings.bind(self.path)["changed"])
        self.assertEqual(self.path.read_text(), once)
        self.assertTrue(bindings.managed(self.path))
        self.assertTrue(bindings.unbind(self.path))
        self.assertEqual(self.path.read_text(), EXISTING)
        self.assertFalse(bindings.managed(self.path))

    def test_rejected_change_restores_the_backup(self):
        self.path.write_text(EXISTING)
        self.reload.side_effect = [["invalid key"], []]
        result = bindings.bind(self.path)
        self.assertFalse(result["changed"])
        self.assertEqual(self.path.read_text(), EXISTING)
        self.assertTrue(any("rejected" in note for note in result["notes"]))

    def test_an_existing_tab_bar_list_is_not_touched(self):
        self.path.write_text('[ui]\ntab_bar_right = [ { type = "zoom" } ]\n')
        result = bindings.bind(self.path)
        self.assertFalse(result["tab_bar"])
        self.assertIn('{ type = "zoom" }', self.path.read_text())

    def test_herdr_defaults_are_never_shadowed(self):
        for key, _, _ in bindings.DEFAULT_BINDINGS:
            self.assertNotIn(key, bindings.HERDR_DEFAULT_KEYS)


if __name__ == "__main__":
    unittest.main()
