# Changelog

All notable changes to Speak. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-11-13

### Added

- opencode support: read its last response and auto-read its finished turns. Speak reads the session Herdr reports from opencode's SQLite database (opencode 2 and 1 layouts), opened read-only.
- A pane's responses play like a playlist, one per turn. ⏮ plays the previous response (or restarts after the first 3 seconds) and ⏭ the next, in the mini player, the panel (`r` / `n`), the media keys, and the new `previous` and `next` actions. The player shows which response it is (`3/5`).
- The mini player follows the agent pane you last worked in, in its tab: with nothing playing, Play reads that pane's latest response, so it works without keys. The panel's Play does the same for the pane it was opened from.

### Changed

- Next (⏭) plays the queue first, then the pane's next response; after the newest it stops. It used to only skip within the queue.
- Previous (⏮) used to always restart the current response.
- Nerd Font icons are now Material Design's media controls (rewind-5, fast-forward-5, skip previous / next), and the mini player draws its controls, settings, and close as bare icons, without button boxes, with play / pause highlighted.

## [0.3.0] - 2026-11-12

### Added

- One-line install: `curl … install.sh | bash` installs the plugin and adds the key bindings and tab bar indicator.
- Speak adds its key bindings to Herdr's config itself (`speak.py bind`, panel Setup tab): only free keys, in one marked block, with a backup and Herdr's reload as a check; `speak.py unbind` removes them.
- Redesigned panel: Player, Auto-read, Voice, Shortcuts, and Setup tabs, with sections, dropdowns, a clickable voice list, and speed steppers. It reopens on the last tab.
- Shortcuts tab listing your Speak key bindings, read from Herdr's `config.toml`.
- Mini player (`mini-player` action): a small pane in the standard media-player layout (title, elapsed · progress · total, restart / back / play-pause / forward / next / stop) that stays open while you work. `prefix+m` brings it to the current tab or workspace, or closes it where it is; optional follow mode moves it whenever you switch tabs.
- Everything in the panel and mini player is clickable; right-click steps settings backwards.
- macOS media keys and Control Center's Now Playing control Speak while it plays (play/pause, next, restart, ±5 s, seek). Speak lets go when idle or after 5 minutes paused. Setting: Setup → macOS.
- Nerd Font icons in Ghostty and plain symbols elsewhere, with an Icons setting.
- The voice loads ahead of time (agent turn start with auto-read on, panel or mini player opening): a cold first read starts in about 0.7 s instead of 4–7 s.
- `r` restarts the current response.
- `read-selection` declares Herdr's `selection` context.

### Changed

- Setup keeps everything in `~/.local/share/herdr-speak`: a uv-managed Python there, no shared uv cache, and a hash-checked uv bootstrap. An environment using an outside Python is rebuilt.
- The runtime adds PyObjC for media controls; existing installs rebuild their runtime in the background on next use. Upgrades use `uv pip sync`, so packages dropped from the lock are removed.
- Auto-read announces the workspace, not the pane label (agents rewrite it).

### Security

- The socket and espeak data never fall back to a shared temp folder (`~/.cache/herdr-speak`, mode 0700, instead), and clients only connect to a socket the user owns.
- Embedded macOS `say` commands (`[[slnc …]]`, `[[volm …]]`) in transcripts are defused; control characters are stripped from titles shown in the panel, mini player, tab bar, and Now Playing.
- Markdown cleanup is bounded on hostile input (link and HTML patterns were quadratic) and capped at 100,000 characters.
- "Read selection" refuses clipboard items a password manager marked as concealed or transient.
- Setup's uv bootstrap moves to uv 0.13.6 (GHSA-hq85-5cpj-mr62) and ignores a system uv older than 0.13.4; downloads are https-only with a size limit.

### Fixed

- The progress bar slid backwards while a response was still synthesizing; the total is now estimated up front and shown as `~` until exact.
- Two responses finishing together could open two audio streams, or close the stream on a queued response.
- Without the runtime, queued auto-reads could cut each other off; stopping now drops them.
- macOS voice list: older-format voices (Alice, Thomas, Luciana, Lekha) were missing, novelty voices weren't, and Siri voices are now excluded.
- Auto-read could read the previous answer when the transcript lagged behind the status change, and marked a response read even when the player failed.
- Transcript lines that are valid JSON but not objects crashed reading.
- Markdown cleanup was quadratic on long lines, removed text such as `Vec<String>`, and leaked nested code fences.
- An invalid `config.json` could fail the install's build step; invalid values now fall back to defaults.
- Long responses no longer copy all synthesized audio for every paragraph.
- Temporary files use the user's private temp folder; concurrent voice downloads no longer collide.
- The mini player could leave orphan copies behind.

## [0.2.0] - 2026-11-12

### Added

- Self-contained setup: Herdr's install step downloads a private Python 3.12, hash-pinned packages, and the checksum-verified Kokoro model and voice into `~/.local/share/herdr-speak`. It bootstraps uv when it's missing.
- Player with pause, resume, back and forward 5 seconds, skip, and a queue.
- Panel (`panel` action) with live playback and every setting.
- Languages: English (US, UK), Spanish, French, Italian, Brazilian Portuguese, and Hindi, with all 54 Kokoro voices downloadable from the panel.
- Model choice: full (325 MB) or small (92 MB).
- Tab bar status line for Herdr's `tab_bar_right`.
- Reading the selection from Herdr's invocation context, with the clipboard as fallback.
- `doctor` and `keybindings` commands.

### Changed

- Plugin id is now `emilapps.speak`, so action names are `emilapps.speak.<action>`.
- The voice no longer depends on the agent-tts plugin.
- macOS speech now plays through the same player, so it can pause and seek too.

### Fixed

- Clipped, flat Kokoro speech: the style vector now matches each chunk's length, and Misaki keeps punctuation.
- Text over about 500 characters no longer fails.

## [0.1.0] - 2026-11-12

### Added

- Read the last pi, Claude Code, or Codex response, or the selection, with macOS speech or Kokoro.
- Opt-in auto-read when an agent finishes a turn.
