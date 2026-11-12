"""User settings, stored as JSON in Herdr's config directory for the plugin."""

from __future__ import annotations

import json

from . import catalog, paths

DEFAULTS = {
    # "auto" uses Kokoro once it is installed and macOS speech until then.
    "engine": "auto",
    "language": catalog.DEFAULT_LANGUAGE,
    "kokoro_voice": None,  # None: the language's recommended voice
    # Not the system voice: when that is a Siri voice, macOS denies processes
    # started by Herdr access to its model files and `say` crashes.
    "say_voice": None,  # None: the language's default macOS voice
    "speed": 1.0,
    "model": "full",  # "full" (325 MB) or "small" (92 MB, slightly lower quality)
    "auto_read": False,  # read each response when its agent finishes a turn
    "auto_panes": "all",  # "all", "background" (panes you aren't viewing), or "focused"
    "announce": True,  # auto-read names the agent and workspace first
    "announce_blocked": False,  # say when an agent waits for approval or input
    "keep_alive_minutes": 10,  # how long the player keeps the voice loaded after speaking
    "icons": "auto",  # "auto" (Nerd Font in Ghostty), "nerd", or "plain"
    "mini_follow": False,  # the mini player moves to the tab you switch to
    "media_keys": True,  # media keys and Control Center control Speak while it plays
}
AUTO_PANES = ["all", "background", "focused"]
AUTO_PANES_LABELS = {"all": "All agents", "background": "Panes I'm not viewing", "focused": "The focused pane"}
SPEEDS = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]


def load() -> dict:
    """Settings with defaults filled in; invalid values fall back to their defaults."""
    config = dict(DEFAULTS)
    try:
        stored = json.loads(paths.CONFIG_FILE.read_text())
    except (OSError, ValueError):
        stored = {}
    if isinstance(stored, dict):
        config.update({key: value for key, value in stored.items() if isinstance(key, str)})
    return sanitize(config)


def sanitize(config: dict) -> dict:
    checks = {
        "engine": lambda v: v in ("auto", "kokoro", "say"),
        "language": lambda v: v in catalog.LANGUAGES,
        "kokoro_voice": lambda v: v is None or v in catalog.KOKORO_VOICES,
        "say_voice": lambda v: v is None or (isinstance(v, str) and v.strip() != ""),
        "speed": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0.5 <= v <= 2.0,
        "model": lambda v: v in catalog.KOKORO_MODELS,
        "auto_read": lambda v: isinstance(v, bool),
        "auto_panes": lambda v: v in AUTO_PANES,
        "announce": lambda v: isinstance(v, bool),
        "announce_blocked": lambda v: isinstance(v, bool),
        "icons": lambda v: v in ("auto", "nerd", "plain"),
        "mini_follow": lambda v: isinstance(v, bool),
        "media_keys": lambda v: isinstance(v, bool),
        "keep_alive_minutes": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 1440,
    }
    for key, valid in checks.items():
        if not valid(config.get(key)):
            config[key] = DEFAULTS[key]
    return config


def save(config: dict) -> None:
    # Keep only keys that differ from the defaults, so later default changes apply.
    changed = {key: value for key, value in config.items() if DEFAULTS.get(key, object()) != value}
    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = paths.CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(changed, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(paths.CONFIG_FILE)


def kokoro_ready(config: dict) -> bool:
    """The runtime, the configured model, and the tokenizer are installed."""
    from . import runtime  # local import: runtime imports this module

    return runtime.runtime_ready() and runtime.model_path(config).exists() and runtime.tokenizer_path().exists()


def resolved_engine(config: dict) -> str:
    engine = config.get("engine")
    if engine == "say":
        return "say"
    # "kokoro" or "auto": Kokoro once installed, macOS speech until then.
    return "kokoro" if kokoro_ready(config) else "say"


def resolved_voice(config: dict, engine: str = "") -> str:
    engine = engine or resolved_engine(config)
    code = config.get("language")
    if engine == "kokoro":
        voice = config.get("kokoro_voice")
        prefix = catalog.language(code)["kokoro"]
        return voice if voice and voice.startswith(prefix) else catalog.default_kokoro_voice(code)
    return config.get("say_voice") or catalog.language(code)["default_say"]


def voice_label(config: dict) -> str:
    engine = resolved_engine(config)
    voice = resolved_voice(config, engine)
    if engine == "kokoro":
        return f"Kokoro {catalog.voice_description(voice)}"
    return f"macOS {voice}"


def speech_settings(config: dict) -> dict:
    """What the player needs to voice one item."""
    engine = resolved_engine(config)
    return {
        "engine": engine,
        "language": config["language"],
        "voice": resolved_voice(config, engine),
        "speed": float(config.get("speed") or 1.0),
        "model": config.get("model") or "full",
    }
