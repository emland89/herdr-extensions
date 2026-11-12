# Repository Guide

Herdr plugins by Emil Landron, published on GitHub as `emland89/herdr-extensions` and installable with `herdr plugin install emland89/herdr-extensions/<dir>`. Each top-level directory with a `herdr-plugin.toml` is a self-contained plugin; `install.sh` links them into the running Herdr server for development.

## Commands

```bash
./install.sh                                        # link every plugin
./install.sh herdr-speak                            # link one plugin
uvx ruff check .                                    # lint (config: ruff.toml)
herdr-speak/scripts/test.sh                         # all herdr-speak tests this machine supports
python3 herdr-speak/speak.py setup                  # install Speak's voice runtime (link skips build steps)
python3 herdr-speak/speak.py doctor                 # Speak's setup and player state
herdr plugin action invoke <action> --plugin <id>   # run an action without a key binding
```

Linked plugins load from this checkout. Manifest edits need `herdr server reload-config`; code edits take effect on the next action, except Speak's player, which keeps running until idle: stop it with `pkill -f herdr_speak.daemon`.

## Conventions

[CONTRIBUTING.md](CONTRIBUTING.md) lists the plugin conventions and the release steps; follow them. In particular:

- Plugin ids are namespaced (`emilapps.<name>`); action names are `<id>.<action>`.
- Speak's launcher (`speak.py` and everything it imports) must run on the macOS system Python 3.9 with only the standard library. Only `herdr_speak/daemon.py` may import runtime packages, and the panel and actions must work before setup.
- Downloads are pinned: Python packages in `requirements.lock` (regenerate with `uv pip compile --universal --python-version 3.12 --generate-hashes requirements.in -o requirements.lock`), model and voice files by sha256 in `herdr_speak/catalog.py`.
- Keep the data directory path short; espeak-ng ignores long data paths.
- Update the plugin's README and CHANGELOG with user-visible changes, and keep `herdr-plugin.toml`'s version equal to `herdr_speak.__version__`.
- Event hooks must return quickly when idle; Herdr starts one process per event.

## Generated Files and Local State

Do not commit caches, logs, virtual environments, `__pycache__`, downloaded models, or user configuration. Speak's runtime and models live in `~/.local/share/herdr-speak`, its state in `~/.local/state/herdr/plugins/emilapps.speak`.
