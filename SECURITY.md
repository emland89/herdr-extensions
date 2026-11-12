# Security

## Reporting a vulnerability

Please report security problems privately through GitHub's [private vulnerability reporting](https://github.com/emland89/herdr-extensions/security/advisories/new) rather than a public issue. Expect a reply within a week.

## What the plugins do on your machine

Herdr plugins run as your user without a sandbox. In this repository:

- **Speak** reads agent transcripts under `~/.pi`, `~/.claude/projects`, and `~/.codex/sessions` and the selection Herdr passes it, and only speaks them. Transcript text is treated as untrusted: it never reaches a shell, embedded `say` commands (`[[...]]`) are defused, control characters are stripped from anything drawn on screen, and parsing is bounded so hostile text can't stall it.
- With no Herdr selection, "read selection" falls back to the clipboard, but refuses anything a password manager marked as concealed or transient (the nspasteboard.org convention).
- Setup downloads pinned files over https only: Python packages from PyPI and GitHub with hashes (`--require-hashes`), uv itself (hash-pinned, used when the system has none or a version older than 0.13.4), and the Kokoro model and voices from Hugging Face, checked by size and sha256. Everything lands in `~/.local/share/herdr-speak`.
- The player listens on a Unix socket in the plugin's state directory (or in `~/.cache/herdr-speak`, mode 0700, when that path is too long), never in a shared temp folder; the socket is mode 0600 and clients only connect to a socket owned by the current user. While playing, the player shows the response title in macOS Now Playing.
- Key setup (the install script, `speak.py bind`, or the panel) edits `~/.config/herdr/config.toml`: one marked block of key bindings and, when you have none, a tab bar entry. It backs the file up first and restores it if Herdr rejects the change. A plain `herdr plugin install` never edits your config.
- Speak sends nothing anywhere else.

Review a plugin's `herdr-plugin.toml` and scripts before installing it; `herdr plugin install` shows a preview.
