#!/usr/bin/env bash
# Run every test that this machine can run.
#   1. Unit tests with the launcher's Python (standard library only).
#   2. Player tests with the runtime's Python (numpy), when setup has installed it.
#   3. The Kokoro integration test runs in step 1 once the model is installed.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -W error::ResourceWarning -m unittest discover -s tests -t . "$@"

runtime="${HERDR_SPEAK_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/herdr-speak}/runtime/venv/bin/python"
if [[ -x "$runtime" ]]; then
  "$runtime" -W ignore -m unittest tests.test_player "$@"
else
  echo "Skipping player tests: run 'python3 speak.py setup' first, or install numpy and run tests/test_player.py." >&2
fi
