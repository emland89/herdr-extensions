"""Integration: synthesize with the real Kokoro model and macOS speech, without playing.

Skipped unless setup has installed the runtime and model (`python3 speak.py setup`).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from herdr_speak import config as settings
from herdr_speak import paths, runtime
from tests.support import ROOT

SCRIPT = r"""
import json, sys
from herdr_speak.daemon import KokoroEngine, SayEngine
results = {}
kokoro = KokoroEngine("full")
for language, voice, text in [("en-us", "af_heart", "Hello from Herdr. Version 2.0 works!"),
                              ("es", "ef_dora", "Hola, ¿cómo estás?")]:
    audio = kokoro.synthesize(text, language, voice, 1.0)
    results[language] = [len(audio) / 24000, float(abs(audio).max())]
long_text = "This sentence is repeated to build a long paragraph. " * 20
results["long"] = [len(kokoro.synthesize(long_text, "en-us", "af_heart", 1.0)) / 24000, 0]
audio = SayEngine().synthesize("Hello", "en-us", "Samantha", 1.0)
results["say"] = [len(audio) / 24000, float(abs(audio).max())]
print(json.dumps(results))
"""


@unittest.skipUnless(runtime.runtime_ready() and settings.kokoro_ready(settings.load()),
                     "Kokoro runtime not installed")
class KokoroIntegrationTest(unittest.TestCase):
    def test_synthesizes_english_spanish_long_text_and_say(self):
        # Run against the installed runtime and model, but download any missing voice into a
        # temporary data folder (linked to the installed model) instead of the live install.
        with tempfile.TemporaryDirectory(prefix="spk-") as directory:
            data = Path(directory)
            (data / "kokoro/voices").mkdir(parents=True)
            for name in ("model.onnx", "tokenizer.json"):
                (data / "kokoro" / name).symlink_to(paths.KOKORO_DIR / name)
            for voice in paths.VOICES_DIR.glob("*.bin"):
                (data / "kokoro/voices" / voice.name).symlink_to(voice)
            env = dict(os.environ, HERDR_SPEAK_DATA_DIR=str(data), HERDR_PLUGIN_STATE_DIR=str(data / "state"))
            result = subprocess.run([str(paths.RUNTIME_PYTHON), "-W", "ignore", "-c", SCRIPT], cwd=str(ROOT),
                                    capture_output=True, text=True, timeout=300, env=env)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        results = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreater(results["en-us"][0], 1.0)
        self.assertGreater(results["en-us"][1], 0.01)
        self.assertGreater(results["es"][0], 0.8)
        # Over 510 phonemes: split into chunks instead of failing or truncating (~45 s of speech).
        self.assertGreater(results["long"][0], 30)
        self.assertGreater(results["say"][0], 0.2)


if __name__ == "__main__":
    unittest.main(argv=sys.argv)
