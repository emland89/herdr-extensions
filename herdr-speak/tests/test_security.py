"""Local security properties: private paths, socket ownership, clipboard secrets."""

import os
import socket
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from herdr_speak import client, herdr, paths
from tests.support import isolate


class PrivatePathsTest(unittest.TestCase):
    def setUp(self):
        base = isolate(self)
        patch = mock.patch.object(paths, "HOME", base)
        patch.start()
        self.addCleanup(patch.stop)

    def test_private_dir_is_owned_and_closed(self):
        directory = paths.private_dir()
        info = directory.lstat()
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o700)
        self.assertEqual(info.st_uid, os.getuid())

    def test_long_state_paths_never_fall_back_to_a_shared_temp_dir(self):
        with mock.patch.object(paths, "STATE_DIR", Path("/x" * 60)):
            path = paths.socket_path()
        self.assertEqual(path.parent, paths.HOME / ".cache" / "herdr-speak")  # private, not a shared temp dir

    def test_private_dir_rejects_a_symlink(self):
        (paths.HOME / ".cache").mkdir()
        (paths.HOME / ".cache" / "herdr-speak").symlink_to(tempfile.gettempdir())
        with self.assertRaises(RuntimeError):
            paths.private_dir()


class SocketOwnershipTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        paths.STATE_DIR.mkdir(parents=True)

    def test_only_a_real_socket_counts(self):
        target = paths.socket_path()
        self.assertFalse(client._own_socket(target))
        target.write_text("not a socket")
        self.assertFalse(client._own_socket(target))
        with self.assertRaises(client.PlayerUnavailable):
            client.request({"command": "status"})
        target.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(target))
        self.assertTrue(client._own_socket(target))


class ClipboardTest(unittest.TestCase):
    def run_types(self, types):
        result = mock.Mock(stdout="\n".join(types))
        with mock.patch("herdr_speak.herdr.subprocess.run", return_value=result):
            return herdr.clipboard_is_secret()

    def test_password_manager_items_are_secret(self):
        self.assertTrue(self.run_types(["public.utf8-plain-text", "org.nspasteboard.ConcealedType"]))
        self.assertTrue(self.run_types(["public.utf8-plain-text", "org.nspasteboard.TransientType"]))
        self.assertFalse(self.run_types(["public.utf8-plain-text"]))

    def test_selection_refuses_a_secret_clipboard(self):
        with mock.patch.object(herdr, "invocation_context", return_value={}), \
                mock.patch.object(herdr, "clipboard_is_secret", return_value=True), \
                self.assertRaisesRegex(RuntimeError, "password manager"):
            herdr.selected_text()

    def test_herdr_selection_is_used_without_touching_the_clipboard(self):
        with mock.patch.object(herdr, "invocation_context", return_value={"selected_text": "hello"}), \
                mock.patch.object(herdr, "clipboard_is_secret") as secret:
            self.assertEqual(herdr.selected_text(), "hello")
        secret.assert_not_called()


if __name__ == "__main__":
    unittest.main()
