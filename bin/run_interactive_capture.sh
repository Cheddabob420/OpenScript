#!/usr/bin/env bash
# Wrapper to run the interactive capture script using the project's virtualenv
set -euo pipefail

PROJECT_DIR="/home/cogy/projects/Openscript"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
SCRIPT="$PROJECT_DIR/build_zone/interactive_capture.py"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Runs the interactive capture helper (hotkey: Ctrl+Meta+S by default).

If pynput is unavailable the script will prompt and you can press Enter to start a capture.
Assign this script to a desktop shortcut or keybinding using the full path:
  $0

EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -x "$PY" ]; then
  echo "ERROR: Python executable not found at $PY" >&2
  exit 2
fi

if [ ! -f "$SCRIPT" ]; then
  echo "ERROR: interactive_capture.py not found at $SCRIPT" >&2
  exit 2
fi

exec "$PY" "$SCRIPT" "$@"
