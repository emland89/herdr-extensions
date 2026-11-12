#!/usr/bin/env bash
# Link this repository's Herdr plugins into the running Herdr server.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
herdr_bin="${HERDR_BIN:-herdr}"

usage() {
  cat <<'EOF'
Usage: ./install.sh [plugin-dir...]

Links each plugin directory (one containing herdr-plugin.toml) with
`herdr plugin link`. With no arguments, every plugin in the repository is
linked. Plugins that are already linked from this repository are skipped.

Key bindings stay in your own ~/.config/herdr/config.toml; each plugin's
README lists the bindings to add.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (($#)); then
  plugins=("$@")
else
  plugins=()
  for manifest in "$repo_dir"/*/herdr-plugin.toml; do
    plugins+=("$(dirname "$manifest")")
  done
fi

linked_roots="$("$herdr_bin" plugin list --json | python3 -I -c '
import json, sys
for plugin in json.load(sys.stdin)["result"]["plugins"]:
    print(plugin.get("plugin_root", ""))
')"

for plugin in "${plugins[@]}"; do
  plugin="$(cd "$plugin" && pwd)"
  if [[ ! -f "$plugin/herdr-plugin.toml" ]]; then
    echo "Skipping $plugin: no herdr-plugin.toml" >&2
    continue
  fi
  if grep -qxF "$plugin" <<<"$linked_roots"; then
    echo "Already linked: $plugin"
    continue
  fi
  echo "Linking $plugin"
  "$herdr_bin" plugin link "$plugin"
done
