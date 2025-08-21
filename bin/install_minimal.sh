#!/usr/bin/env bash
set -euo pipefail

# Minimal installer for Openscript (source-only)
# - creates a virtualenv at .venv
# - upgrades pip and installs packages from requirements.txt
# - makes helper scripts executable and installs desktop file
# This deliberately does NOT register GNOME keybindings or touch system settings.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
  echo "python3 not found; please install Python 3.8+" >&2
  exit 2
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv at .venv..."
  "$PY" -m venv .venv
else
  echo "Using existing .venv"
fi

echo "Upgrading pip and installing requirements..."
.venv/bin/python -m pip install --upgrade pip setuptools wheel
if [ -f requirements.txt ]; then
  .venv/bin/pip install -r requirements.txt
else
  echo "No requirements.txt found; skipping pip install"
fi

if [ -f bin/run_interactive_capture.sh ]; then
  chmod +x bin/run_interactive_capture.sh || true
fi

DESKTOP_DEST="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DEST"
if [ -f build_zone/openscript-interactive-capture.desktop ]; then
  cp build_zone/openscript-interactive-capture.desktop "$DESKTOP_DEST/"
  echo "Installed desktop file to $DESKTOP_DEST"
fi

echo "Minimal install complete. Run the interactive capture with:"
echo "  $PROJECT_DIR/bin/run_interactive_capture.sh"
