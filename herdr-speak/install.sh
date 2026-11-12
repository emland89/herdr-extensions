#!/usr/bin/env bash
# Install Speak for Herdr: the plugin, its local voice, key bindings, and tab bar indicator.
#
#   curl -fsSL https://raw.githubusercontent.com/emland89/herdr-extensions/main/herdr-speak/install.sh | bash
#
# Re-running updates Speak. Set SPEAK_NO_BIND=1 to skip the key bindings; remove them
# later from the panel (Setup tab) or with `python3 <plugin folder>/speak.py unbind`.
set -euo pipefail

SOURCE="${SPEAK_SOURCE:-emland89/herdr-extensions/herdr-speak}"
ID="emilapps.speak"

fail() { echo "speak: $*" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || fail "Speak supports macOS only."
command -v herdr >/dev/null 2>&1 || fail "Herdr isn't installed: https://herdr.dev/docs/install/"
command -v python3 >/dev/null 2>&1 || fail "python3 is missing; install the Command Line Tools: xcode-select --install"

plugin_root() {
  herdr plugin list --json 2>/dev/null | python3 -c '
import json, sys
plugins = json.load(sys.stdin).get("result", {}).get("plugins", [])
print(next((p.get("plugin_root", "") for p in plugins if p.get("plugin_id") == sys.argv[1]), ""))' "$ID"
}

if [ -n "$(plugin_root)" ]; then
  echo "Updating Speak (the voice is reused; this is quick)..."
  herdr plugin update "$ID" --yes || true  # a linked development copy isn't updated: that's fine
else
  echo "Installing Speak. Setup downloads the voice (about 700 MB), so this takes a few minutes..."
  herdr plugin install "$SOURCE" --yes
fi

ROOT="$(plugin_root)"
[ -n "$ROOT" ] || fail "Herdr didn't register the plugin; see: herdr plugin list"

if [ "${SPEAK_NO_BIND:-}" != 1 ]; then
  python3 "$ROOT/speak.py" bind
fi
python3 "$ROOT/speak.py" doctor | sed -n '3,6p'

cat <<'DONE'

Speak is ready. In a pane running pi, Claude Code, or Codex:
  prefix+t        read the last response (again to stop)
  prefix+a        read the selection
  prefix+shift+a  the Speak panel: auto-read, voices, and more
  prefix+m        the mini player
DONE
