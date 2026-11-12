# Speak

Hear your coding agents. Speak is a [Herdr](https://herdr.dev) plugin that reads pi, Claude Code, and Codex responses aloud with a natural voice that runs entirely on your Mac.

- **Read the last response** of the focused agent, or **the text you selected** (or the clipboard, never a password manager's item).
- **Auto-read** (off by default): hear each response as soon as its agent finishes, queued when several finish together.
- **Player**: pause, resume, jump back or forward 5 seconds, skip to the next response, from Herdr keys, a clickable panel, a mini player pane that stays open while you work, or the Mac's media keys and Control Center.
- **Natural local voice**: [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), 54 voices in 7 languages, offline after setup. macOS voices work too.
- **Indicator** in Herdr's tab bar while speaking and when auto-read is on.
- Code blocks, tables, links, and markdown are cleaned up so responses sound natural.

## Quick start

1. Install: `herdr plugin install emland89/herdr-extensions/herdr-speak`
2. Add the [key bindings](#key-bindings) below to `~/.config/herdr/config.toml` and run `herdr server reload-config`.
3. In a pane running pi, Claude Code, or Codex, press `prefix+t` to hear the last response. `prefix+shift+a` opens the panel, where you can turn on auto-read and pick a voice.

## Install

```bash
herdr plugin install emland89/herdr-extensions/herdr-speak
```

Herdr shows the plugin's commands for review, then runs its setup step, which downloads the Kokoro voice (about 700 MB including its own Python, a few minutes) into `~/.local/share/herdr-speak`. Nothing else on your system changes: Python, packages, and the download cache all stay in that folder. If setup can't finish (for example offline), the install still succeeds: Speak uses macOS speech until you install the voice from the panel.

Requirements: macOS 13 or newer, Herdr 0.9.5 or newer, and `python3` 3.9+ (included with the Xcode Command Line Tools). Setup brings its own Python 3.12 and packages; it uses [uv](https://docs.astral.sh/uv/) when installed and fetches it otherwise.

### Key bindings

Herdr plugins can't add key bindings, so add these to `~/.config/herdr/config.toml` and run `herdr server reload-config` (or print them with `python3 speak.py keybindings` from the plugin folder):

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "emilapps.speak.read-last"
description = "Speak: read last response (again to stop)"

[[keys.command]]
key = "prefix+a"
type = "plugin_action"
command = "emilapps.speak.read-selection"
description = "Speak: read selection (again to stop)"

[[keys.command]]
key = "prefix+shift+a"
type = "plugin_action"
command = "emilapps.speak.panel"
description = "Speak: player and settings"

[[keys.command]]
key = "prefix+space"
type = "plugin_action"
command = "emilapps.speak.toggle-pause"
description = "Speak: pause / resume"

[[keys.command]]
key = "prefix+comma"
type = "plugin_action"
command = "emilapps.speak.back"
description = "Speak: back 5 seconds"

[[keys.command]]
key = "prefix+period"
type = "plugin_action"
command = "emilapps.speak.forward"
description = "Speak: forward 5 seconds"

[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "emilapps.speak.mini-player"
description = "Speak: mini player"
```

The plugin's actions are `read-last`, `read-selection`, `panel`, `mini-player`, `toggle-pause`, `back`, `forward`, `skip`, `stop`, and `toggle-auto`. Bind any of them, or run one without a key: `herdr plugin action invoke panel --plugin emilapps.speak`. The panel lists the keys you've bound.

Herdr's Settings screen and right-click menus can't show plugin items (their contents are fixed in Herdr), so Speak's settings live in its panel and "read selection" needs a key. `read-selection` declares Herdr's `selection` context, ready for a future Herdr that offers selection actions in a menu.

### Tab bar indicator

Add this entry to `tab_bar_right` under `[ui]` to see what's playing (`▶ Claude in api 0:42`) and whether auto-read is on (`♪ auto-read`):

```toml
[ui]
tab_bar_right = [
  { type = "command", command = "cat \"$HOME/.local/state/herdr/plugins/emilapps.speak/statusline\" 2>/dev/null", interval_seconds = 1, timeout_seconds = 1 },
]
```

## The panel

`prefix+shift+a` opens Speak's panel in a popup. It has five tabs; click one or press `1`–`5` or `Tab`:

| Tab | What's there |
|---|---|
| Player | What's playing with a progress bar, the playback controls, and quick voice, speed, and auto-read settings |
| Auto-read | Auto-read on or off, which panes to read (dropdown), and announcements |
| Voice | Language (dropdown), every voice for it in a clickable list, speed, and model (dropdown) |
| Shortcuts | Your Speak key bindings, read from Herdr's config, and the panel's own keys |
| Setup | Kokoro status, install or repair, installed files, and the icon style |

Everything is clickable. Right-click steps a setting backwards. Dropdowns open on click and also take `↑` `↓` `Enter`; `Esc` closes an open dropdown, then the panel. Changes are saved immediately, and the panel reopens on the tab you left.

The letter keys work on every tab:

| Key | |
|---|---|
| `space` | Pause or resume |
| `←` / `→` | Back or forward 5 seconds |
| `r` / `n` / `x` | Restart this response / skip to the next / stop and clear the queue |
| `t` | Play a sample of the current voice |
| `a` | Auto-read new responses: on or off |
| `f` | Auto-read from all agents, only panes you aren't viewing, or only the focused pane |
| `m` | Say the agent and workspace before each response, such as "Claude in api" |
| `b` | Say "… needs your input" when an agent waits for approval or an answer |
| `l` | Language |
| `v` | Voice: the language's Kokoro voices, then its installed macOS voices |
| `s` | Speed, 0.8× to 1.5× |
| `o` | Model: full (325 MB, best) or small (92 MB) |
| `p` | Mini player follows you between tabs |
| `k` | Media keys and Control Center control Speak |
| `i` | Install or repair the Kokoro voice |

Shift with a letter cycles backwards; `q` closes the panel. Kokoro voices download on first use (about 0.5 MB each).

The popup takes the keyboard while it's open. To keep controls on screen while you work, use the mini player.

## The mini player

`prefix+m` opens a small pane below the focused one. Pressed in another tab or workspace, it brings the mini player there; pressed where it already is, it closes it. It's laid out like a media player's mini mode:

```
 ▶ Claude in api  +1                                  ⚡ auto ● on   ⚙   ✕
 0:42 ━━━━━━━━━━━━━━━━━━━━━━━━━──────────────────────────────────── 1:30
                          ⏮   ⏪    ⏸    ⏩   ⏭   ⏹
```

The controls are restart, back 5 seconds, play/pause (it shows pause while playing and play otherwise), forward 5 seconds, next response, and stop. The top row has the auto-read toggle, the panel (⚙), and close. Click them, or focus the pane and use the panel's keys. (The drawing shows emoji; Speak draws [icons](#icons) that are one cell wide.)

The mini player is an ordinary Herdr pane, so you can move or resize it, and it lives in one tab. Turn on **follows you between tabs** (panel, Player tab, or `p`) to have it move to whichever tab or workspace you switch to; it's off by default because it changes the layout of the tab you arrive in. Playback itself never depends on the pane: closing it or switching away leaves speech playing, and the keys and the tab bar line work everywhere.

The time shows `~1:30` while a response is still being synthesized: the total is estimated from the text and refined as audio arrives, so the progress bar only moves forward.

## Media keys and Control Center

While Speak plays, it is the Mac's "now playing" app: the keyboard's play/pause key, headphone buttons, and Control Center's Now Playing control it, from any app and any Herdr tab. Control Center shows the agent, workspace, progress, and length.

| Control | Does |
|---|---|
| Play/pause key | Pause or resume |
| Next track (⏭) | Skip to the next queued response |
| Previous track (⏮) | Restart the current response |
| Control Center skip buttons | Back or forward 5 seconds |
| Dragging the position | Seek |

When nothing is playing, or after 5 minutes paused, Speak lets go and the keys go back to Music and other players. Turn it off in the panel under Setup → macOS (`k`).

## Icons

Speak uses [Nerd Font](https://www.nerdfonts.com) icons when it runs in Ghostty, which includes them, and plain Unicode symbols elsewhere. Change it in the panel under Setup → Appearance → Icons: Auto, Nerd Font (for any terminal with a Nerd Font), or Plain symbols. Both sets are one cell per icon, so click targets line up in every terminal; the tab bar line uses the same set.

## How it works

- **Last response**: Herdr reports which agent runs in the pane and its session; Speak reads the agent's own transcript, not the screen, so it gets the whole response even when it scrolled away.

  | Agent | Transcript |
  |---|---|
  | pi | the session file Herdr reports |
  | Claude Code | `~/.claude/projects/*/<session id>.jsonl` |
  | Codex | the rollout for the session, or the newest one for the pane's directory |

- **Auto-read** listens to Herdr's `pane.agent_status_changed` event and reads a response when its agent goes from working to idle or done. Viewing a finished pane doesn't read it again, and the same response is never read twice. Manual reads replace whatever is playing; auto-reads queue.
- **Playback**: a small player process keeps the voice loaded, synthesizes one paragraph ahead of what you hear, and exits after 10 minutes without speech (`keep_alive_minutes`). Speak loads the voice ahead of time, when an agent starts a turn with auto-read on and when the panel or mini player opens, so speech starts in under a second. A read with nothing pre-loaded waits a few seconds once.

## Languages and voices

Kokoro voices exist for English (US and UK), Spanish, French, Italian, Brazilian Portuguese, and Hindi. Changing the language also switches the voice and the phrases Speak adds ("Code block skipped."). Japanese and Chinese Kokoro voices need extra language packages and aren't supported yet.

macOS voices for the language appear after the Kokoro ones. For better macOS voices, download Premium or Enhanced voices in System Settings → Accessibility → Spoken Content → System voice → Manage Voices. Siri voices don't work: macOS refuses them to processes started by Herdr.

## Configuration

Settings live in `config.json` in the plugin's config directory (`herdr plugin config-dir emilapps.speak`). The panel edits them; every key is optional:

```json
{
  "engine": "auto",
  "language": "en-us",
  "kokoro_voice": "af_heart",
  "say_voice": "Samantha",
  "speed": 1.0,
  "model": "full",
  "auto_read": false,
  "auto_panes": "all",
  "announce": true,
  "announce_blocked": false,
  "keep_alive_minutes": 10,
  "icons": "auto",
  "mini_follow": false,
  "media_keys": true
}
```

`engine` is `auto` (Kokoro once installed, macOS speech until then), `kokoro`, or `say`. `auto_panes` is `all`, `background`, or `focused`. `icons` is `auto`, `nerd`, or `plain`.

## Privacy

Speech is synthesized on your Mac. Speak sends nothing anywhere; the only network access is setup downloading pinned, checksum-verified files over https from Hugging Face (the model and voices), PyPI, and GitHub (packages). Transcripts are read, never modified, and treated as untrusted text. "Read selection" uses Herdr's selection, or else the clipboard, and refuses clipboard items a password manager marked as concealed. See [SECURITY.md](../SECURITY.md).

## Files and uninstalling

| Location | Contents |
|---|---|
| `~/.local/share/herdr-speak` | Runtime, Python, model, and voices (about 700 MB) |
| `herdr plugin config-dir emilapps.speak` | `config.json` |
| `~/.local/state/herdr/plugins/emilapps.speak` | Player status, the tab bar line, and `speak.log` |

```bash
herdr plugin uninstall emilapps.speak
rm -rf ~/.local/share/herdr-speak   # Herdr keeps plugin data; remove the voice too
```

## Troubleshooting

- `python3 speak.py doctor` (in the plugin folder, `herdr plugin list` shows it) prints the setup, the voice, and the player state.
- Errors appear as Herdr notifications and in `speak.log` in the state folder. Setup writes `~/.local/share/herdr-speak/setup.log`.
- "Herdr hasn't reported a session": the agent's Herdr integration isn't installed or the agent hasn't started a session yet. See `herdr integration`.
- No sound: check the Mac's output device; the player uses the default device at the moment speech starts.
- The play/pause key controls Speak instead of Music: Speak is the "now playing" app while it has something queued or paused (up to 5 minutes paused). Press `x` in the panel to stop, or turn media keys off under Setup → macOS.
- The first read takes a few seconds: nothing was pre-loaded (Speak loads the voice when an agent starts a turn with auto-read on, or when the panel or mini player opens). Later reads start in under a second.
- After updating the plugin, speech briefly uses a macOS voice: the update changed the voice runtime, which rebuilds in the background (a notification says so).

## Development

```bash
herdr plugin link .                 # use this checkout (link skips the build step)
python3 speak.py setup              # install the voice runtime
scripts/test.sh                     # unit tests, player tests, and the Kokoro integration test
```

The code is in `herdr_speak/`: `commands.py` dispatches Herdr's actions, `autoread.py` handles events, `panel.py` draws the panel, `runtime.py` installs everything, and `daemon.py` is the player. Only the player uses packages outside Python's standard library, and it runs in the runtime environment. See [docs/architecture.md](docs/architecture.md).

## Credits

[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad (Apache 2.0), its [ONNX export](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX), [Misaki](https://github.com/hexgrad/misaki) (Apache 2.0), [espeak-ng](https://github.com/espeak-ng/espeak-ng) (GPL 3.0, downloaded at setup), [ONNX Runtime](https://onnxruntime.ai) (MIT), [spaCy](https://spacy.io) (MIT), [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT), [PyObjC](https://github.com/ronaldoussoren/pyobjc) (MIT), and [uv](https://github.com/astral-sh/uv) (MIT/Apache 2.0). Speak is MIT licensed.
