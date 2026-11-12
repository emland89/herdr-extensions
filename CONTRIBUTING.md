# Contributing

Thanks for helping. Issues and pull requests are welcome.

## Plugin conventions

These follow Herdr's [plugin guide](https://herdr.dev/docs/plugins/):

- **One directory per plugin** with its `herdr-plugin.toml`, code, tests, README, CHANGELOG, and LICENSE, so `herdr plugin install emland89/herdr-extensions/<dir>` works on its own.
- **Namespaced ids** (`emilapps.<name>`) so action names don't collide with other plugins.
- **Call Herdr through `HERDR_BIN_PATH`**, not a hard-coded `herdr`.
- **Files**: user settings in `HERDR_PLUGIN_CONFIG_DIR`, runtime state in `HERDR_PLUGIN_STATE_DIR`, never in the plugin folder (installed plugins are managed checkouts). Large downloads go in a plugin-named folder under `~/.local/share` so build steps, which get no plugin directories, can find them too.
- **Build steps never fail the install** for optional pieces; degrade and let the user retry.
- **Pin and verify downloads**: exact versions with hashes for packages, sha256 for files.
- **No key bindings from installers**; document them in the README.
- **Report failures** with `herdr notification show`, and log details to the state directory.
- **Treat agent transcripts and pane contents as untrusted data**: read and speak or display them, never execute them.
- **Event hooks return fast** when the plugin has nothing to do: Herdr starts a process per event.

## Checks

```bash
uvx ruff check .
herdr-speak/scripts/test.sh
```

There is no hosted CI; run the checks locally before committing. `scripts/test.sh` runs the unit tests, the player tests (with the runtime's Python, after `python3 herdr-speak/speak.py setup`), and the Kokoro integration test once the model is installed. Run the unit tests on the oldest supported Python too, since the launcher must work on the macOS system Python: `uv run --no-project --python 3.9 python -m unittest discover -s tests -t .` from `herdr-speak`.

Test changes in Herdr itself too: link the plugin with `./install.sh`, run `herdr server reload-config` after manifest changes, and try the actions (`herdr plugin action invoke <action> --plugin <id>` runs one without a key).

## Releases

1. Update the version in `herdr-plugin.toml` and the plugin's `__version__`; a test checks they match.
2. Move the CHANGELOG's notes under the new version.
3. Merge to `main` and tag `<plugin>-v<version>` (for example `speak-v0.2.0`).

Users get updates with `herdr plugin update`. Changing a pinned dependency (`requirements.lock`) makes Speak rebuild its runtime on the next setup.
