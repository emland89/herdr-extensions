"""Drive the panel through a pseudo-terminal, as Herdr's popup would."""

import json
import os
import pty
import re
import select
import sys
import time
import unittest

from herdr_speak import paths
from tests.support import ROOT, isolate


class PanelTest(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def run_panel(self, keys):
        pid, fd = pty.fork()
        if pid == 0:  # child: the panel, with this test's isolated directories
            os.execve(sys.executable, [sys.executable, str(ROOT / "speak.py"), "panel"], dict(os.environ))
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
        for key in keys:
            os.write(fd, key)
            drain(0.4)
        try:
            os.write(fd, b"q")
        except OSError:  # the panel already closed
            pass
        drain(0.5)
        _, code = os.waitpid(pid, 0)
        os.close(fd)
        self.assertEqual(code, 0)
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", screen.decode(errors="ignore"))

    def test_settings_keys_update_the_config(self):
        screen = self.run_panel([b"a", b"f", b"s", b"s", b"S", b"m", b"l"])
        self.assertIn("Speak", screen)
        self.assertIn("Auto-read", screen)
        config = json.loads(paths.CONFIG_FILE.read_text())
        self.assertEqual(config, {"auto_read": True, "auto_panes": "background", "speed": 1.1,
                                  "announce": False, "language": "en-gb"})
        self.assertEqual(paths.STATUSLINE_FILE.read_text(), "♪ auto-read\n")

    def test_escape_closes(self):
        self.run_panel([b"\x1b"])


if __name__ == "__main__":
    unittest.main()
