# Herdr Extensions

Plugins for [Herdr](https://herdr.dev), the terminal workspace manager for coding agents.

| Plugin | What it does | Platforms |
|---|---|---|
| [Speak](herdr-speak/README.md) | Hear your coding agents: reads pi, Claude Code, and Codex responses aloud with a natural local voice, auto-reads finished turns, and plays with pause and seek. | macOS |

## Install a plugin

```bash
herdr plugin install emland89/herdr-extensions/herdr-speak
```

Herdr previews the plugin's commands before running anything. Each plugin's README covers its key bindings and settings; Herdr plugins can't add key bindings themselves.

## Develop

Clone the repository and link the plugins, so Herdr runs them from your checkout:

```bash
git clone https://github.com/emland89/herdr-extensions.git
cd herdr-extensions
./install.sh               # link every plugin (or: ./install.sh herdr-speak)
```

`herdr plugin link` skips build steps, so run a plugin's setup yourself when it has one (Speak: `python3 herdr-speak/speak.py setup`). Unlink with `herdr plugin unlink <plugin-id>`.

Run the checks before sending a change:

```bash
uvx ruff check .
herdr-speak/scripts/test.sh
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and releases, and [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[MIT](LICENSE)
