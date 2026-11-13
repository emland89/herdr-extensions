"""Config, catalog, and status line."""

import json
import unittest
from unittest import mock

from herdr_speak import catalog, icons, paths, status
from herdr_speak import config as settings
from tests.support import isolate

SAY_LISTING = """\
Albert              en_US    # Hello! My name is Albert.
Alice               it_IT    # Ciao! Mi chiamo Alice.
Aman (English (India)) en_IN    # Hi, I’m Siri!
Ava (Premium) (English (US)) en_US    # Hello! My name is Ava.
Daniel (English (UK)) en_GB    # Hello! My name is Daniel.
Eddy (English (US)) en_US    # Hello! My name is Eddy.
Lekha               hi_IN    # नमस्ते, मेरा नाम लेखा है।
Mónica (Spanish (Spain)) es_ES    # ¡Hola! Me llamo Mónica.
Nora (English (US)) en_US    # Hi, I’m Siri!
Samantha (English (US)) en_US    # Hello! My name is Samantha.
Samantha (English (US)) en_US    # Hi, I'm Siri!
"""


class ConfigTest(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def test_saves_only_changed_keys(self):
        config = settings.load()
        config["auto_read"] = True
        settings.save(config)
        self.assertEqual(json.loads(paths.CONFIG_FILE.read_text()), {"auto_read": True})
        self.assertTrue(settings.load()["auto_read"])

    def test_invalid_files_and_values_fall_back_to_defaults(self):
        paths.CONFIG_DIR.mkdir(parents=True)
        for content in ("1", "[]", "not json", '"x"'):
            paths.CONFIG_FILE.write_text(content)
            self.assertEqual(settings.load(), settings.DEFAULTS)
        paths.CONFIG_FILE.write_text('{"model": "tiny", "speed": "fast", "auto_read": "yes", "auto_panes": 3, "speed2": 1}')
        config = settings.load()
        self.assertEqual((config["model"], config["speed"], config["auto_read"], config["auto_panes"]),
                         ("full", 1.0, False, "all"))

    def test_unknown_language_falls_back_to_default(self):
        paths.CONFIG_DIR.mkdir(parents=True)
        paths.CONFIG_FILE.write_text('{"language": "xx"}')
        self.assertEqual(settings.load()["language"], catalog.DEFAULT_LANGUAGE)

    def test_engine_uses_kokoro_only_once_installed(self):
        config = settings.load()
        with mock.patch.object(settings, "kokoro_ready", return_value=False):
            self.assertEqual(settings.speech_settings(config)["engine"], "say")
            self.assertEqual(settings.speech_settings(config)["voice"], "Samantha")
        with mock.patch.object(settings, "kokoro_ready", return_value=True):
            self.assertEqual(settings.speech_settings(config)["voice"], "af_heart")
            config["engine"] = "say"
            self.assertEqual(settings.speech_settings(config)["engine"], "say")

    def test_voice_follows_language(self):
        config = dict(settings.load(), language="es", kokoro_voice="af_heart")
        # A voice from another language is replaced by the language's recommended voice.
        self.assertEqual(settings.resolved_voice(config, "kokoro"), "ef_dora")
        self.assertEqual(settings.resolved_voice(config, "say"), "Mónica")


class CatalogTest(unittest.TestCase):
    def test_say_voices_skip_novelty_voices_and_duplicates(self):
        # Default first, then the language's own voices, then multilingual ones; no novelty or Siri-only voices.
        self.assertEqual(catalog.say_voices_for("en-us", SAY_LISTING), ["Samantha", "Ava (Premium)", "Eddy"])
        self.assertEqual(catalog.say_voices_for("es", SAY_LISTING), ["Mónica"])
        # Older listings have no language suffix.
        self.assertEqual(catalog.say_voices_for("it", SAY_LISTING), ["Alice"])
        self.assertEqual(catalog.say_voices_for("hi", SAY_LISTING), ["Lekha"])

    def test_every_language_has_a_default_kokoro_voice_and_phrases(self):
        for code, info in catalog.LANGUAGES.items():
            self.assertIn(catalog.default_kokoro_voice(code), catalog.KOKORO_VOICES, code)
            for key in ("code", "table", "link", "in", "needs_input", "sample"):
                self.assertTrue(info[key], f"{code}.{key}")

    def test_voice_checksums_look_like_sha256(self):
        for name, digest in catalog.KOKORO_VOICES.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)

    def test_voice_description(self):
        self.assertEqual(catalog.voice_description("am_michael"), "Michael (male)")


class StatusLineTest(unittest.TestCase):
    def setUp(self):
        isolate(self)

    def test_render(self):
        plain = {"icons": "plain"}
        self.assertEqual(status.render(dict(plain, auto_read=False), {"state": "idle"}), "")
        self.assertEqual(status.render(dict(plain, auto_read=True), {"state": "idle"}), "♪ auto-read")
        playing = {"state": "playing", "title": "Claude in work", "position": 75, "queued": 2}
        self.assertEqual(status.render(dict(plain, auto_read=True), playing), "▶ Claude in work 1:15 +2 · ↻")
        self.assertTrue(status.render(plain, dict(playing, state="paused")).startswith("‖"))
        self.assertTrue(status.render({"icons": "nerd"}, playing).startswith(icons.NERD["play"]))

    def test_icon_sets_match_and_auto_detects_ghostty(self):
        from herdr_speak import icons

        self.assertEqual(set(icons.NERD), set(icons.PLAIN))
        with mock.patch.dict("os.environ", {"GHOSTTY_RESOURCES_DIR": "/x"}):
            self.assertEqual(icons.resolve("auto"), "nerd")
        with mock.patch.dict("os.environ", {"GHOSTTY_RESOURCES_DIR": "", "TERM_PROGRAM": "herdr"}):
            self.assertEqual(icons.resolve("auto"), "plain")
        self.assertEqual(icons.resolve("plain"), "plain")

    def test_refresh_writes_file_and_ignores_dead_players(self):
        status.write_playback({"state": "playing", "title": "x", "position": 1, "pid": 999999})
        self.assertEqual(status.read_playback(), {"state": "idle"})  # no such process
        self.assertEqual(status.refresh({"auto_read": True, "icons": "plain"}), "♪ auto-read")
        self.assertEqual(paths.STATUSLINE_FILE.read_text(), "♪ auto-read\n")


if __name__ == "__main__":
    unittest.main()
