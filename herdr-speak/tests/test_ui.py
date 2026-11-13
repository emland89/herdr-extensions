"""Input parsing, hotspots, the shortcut list, and clicking through a pseudo-terminal."""

import fcntl
import json
import os
import pty
import re
import select
import struct
import sys
import termios
import time
import unittest
from unittest import mock

from herdr_speak import panel, paths, shortcuts
from herdr_speak.ui import Line, Screen, parse_input
from tests.support import ROOT, isolate

CONFIG_TOML = """\
onboarding = false
[keys]
prefix = "ctrl+a"

[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "emilapps.speak.read-last"

[[keys.command]]
key = "prefix+shift+a"
type = "plugin_action"
command = "emilapps.speak.panel"

[[keys.command]]
key = "prefix+comma"
type = "shell"
command = "emilapps.speak.back"

[[keys.command]]
key = "prefix+x"
type = "plugin_action"
command = "other.plugin.read-last"
"""


class ParseInputTest(unittest.TestCase):
    def test_keys_arrows_and_escape(self):
        self.assertEqual(parse_input("a \x1b[D\x1b[C\x1b"),
                         [("key", "a"), ("key", "space"), ("key", "left"), ("key", "right"), ("key", "escape")])

    def test_mouse_presses_only(self):
        # left press, left release, right press, wheel, motion
        data = "\x1b[<0;10;3M\x1b[<0;10;3m\x1b[<2;4;5M\x1b[<64;1;1M\x1b[<32;2;2M"
        self.assertEqual(parse_input(data), [("click", (0, 10, 3)), ("click", (2, 4, 5))])

    def test_unknown_sequences_are_skipped(self):
        self.assertEqual(parse_input("\x1b[15~x\x1bOPy"), [("key", "x"), ("key", "y")])


class HotspotTest(unittest.TestCase):
    def test_segments_with_keys_become_hotspots(self):
        line = Line().add("  ").add(" Pause ", "\x1b[7m", "space").add(" ").add("Speed", "", "s")
        self.assertEqual(line.hotspots, [(3, 9, "space"), (11, 15, "s")])
        screen = Screen.__new__(Screen)
        screen.hotspots = [(2, first, last, key) for first, last, key in line.hotspots]
        self.assertEqual(screen.hit(5, 2), "space")
        self.assertEqual(screen.hit(15, 2), "s")
        self.assertIsNone(screen.hit(10, 2))
        self.assertIsNone(screen.hit(5, 1))


class TransportTest(unittest.TestCase):
    def setUp(self):
        panel.use_icons({"icons": "plain"})

    def labels(self, state):
        line = panel.transport(state, indent="", labels=False)
        rendered = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line.render())
        return rendered.split(), [key for _, _, key in line.hotspots]

    def test_standard_order_and_play_pause_state(self):
        icons, keys = self.labels("playing")
        self.assertEqual(icons, ["|«", "«", "‖", "»", "»|", "■"])  # restart, back, pause, forward, next, stop
        self.assertEqual(keys, ["r", "left", "space", "right", "n", "x"])
        self.assertEqual(self.labels("paused")[0][2], "▶")
        self.assertEqual(self.labels("idle")[0][2], "▶")
        self.assertEqual(self.labels("buffering")[0][2], "‖")

    def test_idle_buttons_are_live_when_there_is_a_pane_to_play(self):
        dim = panel.transport("idle", indent="", labels=False).render()
        live = panel.transport("idle", indent="", labels=False, ready=True).render()
        self.assertIn(panel.DIM, dim)
        self.assertNotIn(panel.DIM, live)

    def test_prev_and_next_step_through_the_target_pane(self):
        controls = panel.Controls()
        controls.target = "w1:p1"
        with mock.patch("herdr_speak.playlist.previous", return_value="") as previous, \
                mock.patch("herdr_speak.playlist.next_response", return_value="That was the latest response") as nxt:
            self.assertTrue(controls.playback_key("r"))
            wait_for(lambda: not controls.busy)
            self.assertTrue(controls.playback_key("n"))
            wait_for(lambda: not controls.busy)
        previous.assert_called_once_with("w1:p1")
        nxt.assert_called_once_with("w1:p1")
        self.assertIn("latest response", controls.message)

    def test_play_when_idle_reads_the_target_pane(self):
        controls = panel.Controls()
        controls.target = "w1:p1"
        with mock.patch("herdr_speak.client.playback", return_value={"state": "idle"}), \
                mock.patch("herdr_speak.playlist.play") as play:
            controls.playback_key("space")
            wait_for(lambda: not controls.busy)
        play.assert_called_once_with("w1:p1")


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.01)


class MiniRowTest(unittest.TestCase):
    def test_bare_material_icons_in_player_order(self):
        from herdr_speak import icons, mini

        panel.use_icons({"icons": "nerd"})
        line = mini.media_row("playing")
        shown = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line.render()).split()
        self.assertEqual(shown, [icons.NERD[n] for n in ("restart", "back", "pause", "forward", "next", "stop")])
        self.assertEqual([key for _, _, key in line.hotspots], ["r", "left", "space", "right", "n", "x"])
        self.assertNotIn(panel.REVERSE, line.render())  # no button boxes
        self.assertIn(panel.GREEN, line.render())  # play/pause stands out while playing
        self.assertTrue(all(last - first == 2 for first, last, _ in line.hotspots))  # icon plus a cell each side

    def test_settings_and_close_are_bare_icons_too(self):
        from herdr_speak import icons, mini

        panel.use_icons({"icons": "nerd"})
        title = mini.lines({"auto_read": True}, {"state": "idle"}, 100, panel.Controls())[0]
        self.assertNotIn(panel.REVERSE, title.render())
        shown = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", title.render())
        self.assertTrue(shown.endswith(f" {icons.NERD['settings']}    {icons.NERD['close']} "))
        self.assertEqual([key for _, _, key in title.hotspots][-2:], ["s", "q"])

    def test_dim_until_there_is_something_to_play(self):
        from herdr_speak import mini

        panel.use_icons({"icons": "plain"})
        self.assertIn(panel.DIM, mini.media_row("idle").render())
        self.assertNotIn(panel.DIM, mini.media_row("idle", ready=True).render())


class ShortcutsTest(unittest.TestCase):
    def test_reads_only_this_plugins_actions(self):
        prefix, bound = shortcuts.read_bindings(CONFIG_TOML, "emilapps.speak")
        self.assertEqual(prefix, "ctrl+a")
        self.assertEqual(bound, {"read-last": "prefix+t", "panel": "prefix+shift+a"})
        self.assertEqual(shortcuts.read_bindings("", "emilapps.speak"), ("ctrl+b", {}))

    def test_describe_key(self):
        self.assertEqual(shortcuts.describe_key("prefix+t"), "prefix t")
        self.assertEqual(shortcuts.describe_key("prefix+shift+a"), "prefix Shift+A")
        self.assertEqual(shortcuts.describe_key("prefix+comma"), "prefix ,")
        self.assertEqual(shortcuts.describe_key("prefix+space"), "prefix Space")


class ClickThroughTerminalTest(unittest.TestCase):
    """Runs the real panel and mini player in a pseudo-terminal and clicks them with SGR mouse input."""

    def setUp(self):
        base = isolate(self)
        os.environ["XDG_CONFIG_HOME"] = str(base / "xdg")
        self.addCleanup(os.environ.pop, "XDG_CONFIG_HOME", None)
        (base / "xdg/herdr").mkdir(parents=True)
        (base / "xdg/herdr/config.toml").write_text(CONFIG_TOML)

    def run_ui(self, command, actions):
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, str(ROOT / "speak.py"), command], dict(os.environ))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 100, 0, 0))  # rows, columns
        screen = b""

        def drain(seconds):
            nonlocal screen
            deadline = time.time() + seconds
            while time.time() < deadline:
                ready, _, _ = select.select([fd], [], [], 0.05)
                if ready:
                    try:
                        screen += os.read(fd, 65536)
                    except OSError:
                        return

        drain(1.5)
        for action in actions:
            # Wait for what the action needs to be on screen (a tab's first draw can be slow
            # on a busy machine), instead of guessing a fixed delay.
            deadline = time.time() + 8
            while True:
                text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", screen.decode(errors="ignore"))
                try:
                    keys = action(text.split("\r\n"))
                    break
                except AssertionError:
                    if time.time() > deadline:
                        raise
                    drain(0.2)
            os.write(fd, keys.encode())
            drain(0.6)
        try:
            os.write(fd, b"q")
        except OSError:
            pass
        drain(0.5)
        os.waitpid(pid, 0)
        os.close(fd)
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", screen.decode(errors="ignore"))

    @staticmethod
    def click(label, button=0, marker="Speak  ", marker_row=2):
        """Click `label` in the newest frame; `marker` is text on screen row `marker_row` of every frame."""
        def action(lines):
            for row in range(len(lines) - 1, -1, -1):
                if label in lines[row]:
                    start = max(i for i, line in enumerate(lines[: row + 1]) if marker in line)
                    return f"\x1b[<{button};{lines[row].rindex(label) + 1};{row - start + marker_row}M"
            raise AssertionError(f"{label!r} not on screen")
        return action

    def config(self):
        return json.loads(paths.CONFIG_FILE.read_text()) if paths.CONFIG_FILE.exists() else {}

    def test_panel_player_tab_controls(self):
        self.run_ui("panel", [self.click(" + "), self.click(" + "), self.click(" − "), self.click("Auto-read     ")])
        self.assertEqual(self.config(), {"speed": 1.1, "auto_read": True})

    def test_panel_tabs_dropdowns_and_shortcuts(self):
        screen = self.run_ui("panel", [self.click("3 ∿ Voice"), self.click("English (US)"), self.click("English (UK)"),
                                       self.click("2 ↻ Auto-read"), self.click("Say when an agent waits"),
                                       self.click("4 ⌨ Shortcuts")])
        self.assertEqual(self.config(), {"language": "en-gb", "announce_blocked": True})
        self.assertIn("The prefix is ctrl+a", screen)
        self.assertRegex(screen, r"prefix Shift\+A\s+This panel")
        self.assertRegex(screen, r"not bound\s+Mini player")
        self.assertEqual((paths.STATE_DIR / "panel-tab").read_text(), "3")  # reopens on the last tab

    def test_dropdown_keyboard(self):
        self.run_ui("panel", [lambda _: "3", self.click("English (US)"), lambda _: "\x1b[B", lambda _: "\x1b[B",
                              lambda _: "\r"])
        self.assertEqual(self.config(), {"language": "es"})

    def test_mini_player_toggles_auto_read(self):
        self.run_ui("mini", [self.click(" auto ", marker="Nothing playing", marker_row=1)])
        self.assertEqual(self.config(), {"auto_read": True})
        self.assertFalse((paths.STATE_DIR / "mini.json").exists())  # forgotten when it closes


if __name__ == "__main__":
    unittest.main()
