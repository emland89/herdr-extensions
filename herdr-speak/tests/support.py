"""Test helpers: isolated plugin directories and module reloading."""

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from herdr_speak import paths  # noqa: E402


def isolate(test: unittest.TestCase) -> Path:
    """Point every plugin directory at a fresh temporary folder for this test."""
    directory = tempfile.TemporaryDirectory(prefix="speak-test-")
    test.addCleanup(directory.cleanup)
    base = Path(directory.name)
    variables = {
        "HERDR_PLUGIN_STATE_DIR": str(base / "state"),
        "HERDR_PLUGIN_CONFIG_DIR": str(base / "config"),
        "HERDR_SPEAK_DATA_DIR": str(base / "data"),
        "GHOSTTY_RESOURCES_DIR": "",  # "auto" icons resolve to plain symbols, whatever terminal runs the tests
    }
    saved = {name: os.environ.get(name) for name in variables}
    os.environ.update(variables)

    def restore() -> None:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(paths)

    test.addCleanup(restore)
    importlib.reload(paths)
    return base


def write_jsonl(test: unittest.TestCase, entries: list) -> Path:
    directory = tempfile.TemporaryDirectory(prefix="speak-test-")
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "session.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
    return path
