"""Setup: downloads, checksums, and the runtime marker (no network: curl reads file:// URLs)."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from herdr_speak import paths, runtime
from tests.support import isolate


class DownloadTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "blob.bin"
        self.data = b"kokoro" * 1000
        self.source.write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.dest = paths.DATA_DIR / "out" / "blob.bin"

    def test_downloads_and_verifies(self):
        seen = []
        runtime.download(self.source.as_uri(), self.dest, len(self.data), self.sha, lambda s, f: seen.append(f))
        self.assertEqual(self.dest.read_bytes(), self.data)
        self.assertFalse(self.dest.with_name("blob.bin.part").exists())

    def test_resumes_a_partial_download(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.with_name("blob.bin.part").write_bytes(self.data[:1000])
        runtime.download(self.source.as_uri(), self.dest, len(self.data), self.sha)
        self.assertEqual(self.dest.read_bytes(), self.data)

    def test_rejects_a_checksum_mismatch_and_removes_the_partial(self):
        with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
            runtime.download(self.source.as_uri(), self.dest, len(self.data), "0" * 64)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("blob.bin.part").exists())

    def test_skips_a_verified_existing_file(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(self.data)
        runtime.download("file:///nonexistent", self.dest, len(self.data), self.sha)  # would fail if fetched

    def test_unknown_voice_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime.install_voice("xx_nobody")


class RuntimeStateTest(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def test_runtime_ready_requires_matching_lock(self):
        self.assertFalse(runtime.runtime_ready())
        paths.RUNTIME_PYTHON.parent.mkdir(parents=True)
        paths.RUNTIME_PYTHON.write_text("")
        paths.RUNTIME_MARKER.write_text(json.dumps({"lock_sha256": "old"}))
        self.assertFalse(runtime.runtime_ready())  # requirements changed: reinstall
        paths.RUNTIME_MARKER.write_text(json.dumps({"lock_sha256": runtime.lock_digest()}))
        self.assertTrue(runtime.runtime_ready())

    def test_crashed_setup_reports_failure(self):
        paths.DATA_DIR.mkdir(parents=True)
        paths.SETUP_STATUS.write_text(json.dumps({"state": "running", "step": "x"}))
        self.assertEqual(runtime.setup_status()["state"], "failed")

    def test_lock_file_pins_every_package_with_hashes(self):
        lock = runtime.LOCK_FILE.read_text()
        packages = [line for line in lock.splitlines() if line and not line.startswith((" ", "#"))]
        self.assertTrue(packages)
        self.assertNotIn("torch", lock)
        # Every package line is followed by at least one hash line.
        blocks = re.split(r"\n(?=[^ #\n])", lock)
        for block in blocks:
            if block.startswith("#") or not block.strip():
                continue
            self.assertTrue("==" in block.split()[0] or " @ " in block.splitlines()[0], block.splitlines()[0])
            self.assertIn("--hash=sha256:", block, block.splitlines()[0])
        self.assertIn("--hash=sha256:", runtime.BOOTSTRAP_LOCK.read_text())


FAKE_UV = """#!/bin/sh
# Records each call; "venv" creates an environment whose python accepts any import check.
if [ "$1" = --version ]; then echo "uv 0.13.6 (test)"; exit 0; fi
echo "$* | $UV_PYTHON_PREFERENCE | $UV_CACHE_DIR | $UV_PYTHON_INSTALL_DIR" >> "$FAKE_UV_LOG"
for last in "$@"; do :; done
if [ "$1" = venv ]; then
  mkdir -p "$last/bin" "$UV_PYTHON_INSTALL_DIR"
  printf '#!/bin/sh\nexit 0\n' > "$UV_PYTHON_INSTALL_DIR/python3.12"
  chmod +x "$UV_PYTHON_INSTALL_DIR/python3.12"
  ln -s "$UV_PYTHON_INSTALL_DIR/python3.12" "$last/bin/python"
fi
mkdir -p "$UV_CACHE_DIR"
"""


class InstallRuntimeTest(unittest.TestCase):
    def setUp(self):
        base = isolate(self)
        tools = base / "tools"
        tools.mkdir()
        uv = tools / "uv"
        uv.write_text(FAKE_UV)
        uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
        self.log = base / "uv.log"
        saved = {name: os.environ.get(name) for name in ("PATH", "FAKE_UV_LOG")}
        os.environ["PATH"] = f"{tools}:{os.environ['PATH']}"
        os.environ["FAKE_UV_LOG"] = str(self.log)
        self.addCleanup(lambda: [os.environ.__setitem__(k, v) if v is not None else os.environ.pop(k, None)
                                 for k, v in saved.items()])

    def test_installs_inside_the_data_dir_with_hashes_and_sync(self):
        runtime.install_runtime()
        calls = self.log.read_text().splitlines()
        self.assertTrue(calls[0].startswith("venv --quiet --python 3.12"))
        self.assertIn("pip sync --quiet --python", calls[1])
        self.assertIn("--require-hashes", calls[1])
        for call in calls:
            _, preference, cache, python_dir = [part.strip() for part in call.split("|")]
            self.assertEqual(preference, "only-managed")
            self.assertTrue(cache.startswith(str(paths.DATA_DIR)))
            self.assertTrue(python_dir.startswith(str(paths.DATA_DIR)))
        self.assertTrue(runtime.runtime_ready())
        self.assertFalse((paths.DATA_DIR / "cache").exists())  # removed after installing

    def test_rebuilds_an_environment_whose_python_lives_elsewhere(self):
        outside = paths.DATA_DIR.parent / "elsewhere-python"
        outside.write_text("#!/bin/sh\nexit 0\n")
        paths.RUNTIME_PYTHON.parent.mkdir(parents=True)
        paths.RUNTIME_PYTHON.symlink_to(outside)
        paths.RUNTIME_MARKER.write_text(json.dumps({"lock_sha256": runtime.lock_digest(), "python": "3.12"}))
        self.assertFalse(runtime.runtime_ready())
        runtime.install_runtime()
        self.assertTrue(self.log.read_text().startswith("venv"))  # recreated
        self.assertTrue(runtime.runtime_ready())


class UvVersionTest(unittest.TestCase):
    def test_old_system_uv_is_not_used(self):
        base = isolate(self)
        old = base / "uv"
        old.write_text("#!/bin/sh\necho 'uv 0.11.16 (abc 2026-05-21)'\n")
        old.chmod(0o755)
        self.assertEqual(runtime.uv_version(str(old)), (0, 11, 16))
        self.assertLess(runtime.uv_version(str(old)), runtime.MIN_SYSTEM_UV)
        self.assertEqual(runtime.uv_version(str(base / "missing")), (0,))

    def test_bootstrap_pins_a_fixed_uv(self):
        pinned = re.search(r"^uv==([\d.]+)", runtime.BOOTSTRAP_LOCK.read_text(), re.M).group(1)
        self.assertGreaterEqual(tuple(int(x) for x in pinned.split(".")), runtime.MIN_SYSTEM_UV)


class BuildNeverFailsTest(unittest.TestCase):
    def test_build_exits_zero_even_when_setup_cannot_start(self):
        base = isolate(self)
        blocker = base / "not-a-directory"
        blocker.write_text("")
        env = dict(os.environ, HERDR_SPEAK_DATA_DIR=str(blocker / "data"))
        paths.CONFIG_DIR.mkdir(parents=True)
        paths.CONFIG_FILE.write_text("1")  # a corrupt config must not matter either
        speak = [sys.executable, str(runtime.paths.PLUGIN_ROOT / "speak.py"), "setup"]
        build = subprocess.run(speak + ["--build"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(build.returncode, 0, build.stderr)
        manual = subprocess.run(speak, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(manual.returncode, 1)


if __name__ == "__main__":
    unittest.main()
