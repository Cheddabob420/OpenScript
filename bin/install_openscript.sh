#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

usage(){
  cat <<EOF
Usage: $(basename "$0") [--yes]

This script bootstraps Openscript in the current directory:
- creates a Python venv at .venv
- installs packages from requirements.txt
- makes wrapper scripts executable
- installs a desktop file to ~/.local/share/applications/
- (optional) registers a GNOME custom keybinding for Ctrl+Meta+S

Run with --yes to accept automatic GNOME keybinding registration.
EOF
}

CONFIRM=no
if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ]; then
  CONFIRM=yes
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "python3 not found; please install Python 3.8+" >&2
  exit 2
fi

# create venv
if [ ! -d ".venv" ]; then
  echo "Creating virtualenv .venv..."
  "$PY" -m venv .venv
else
  echo "Using existing .venv"
fi

# upgrade pip and install requirements
echo "Installing requirements into .venv..."
.venv/bin/python -m pip install --upgrade pip setuptools wheel
if [ -f requirements.txt ]; then
  .venv/bin/pip install -r requirements.txt
fi

# make wrapper executable
if [ -f bin/run_interactive_capture.sh ]; then
  chmod +x bin/run_interactive_capture.sh || true
fi

# install desktop file
DESKTOP_DEST="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DEST"
if [ -f build_zone/openscript-interactive-capture.desktop ]; then
  cp build_zone/openscript-interactive-capture.desktop "$DESKTOP_DEST/"
  echo "Installed desktop file to $DESKTOP_DEST"
fi

# Optionally register GNOME keybinding
if command -v gsettings >/dev/null 2>&1; then
  if [ "$CONFIRM" != "yes" ]; then
    read -r -p "Register GNOME keybinding for Ctrl+Meta+S now? [y/N]: " yn
    case "$yn" in
      [Yy]*) CONFIRM=yes;;
      *) CONFIRM=no;;
    esac
  fi

  if [ "$CONFIRM" = "yes" ]; then
    echo "Registering GNOME custom keybinding..."
    python3 - <<'PY'
import subprocess, ast
schema = 'org.gnome.settings-daemon.plugins.media-keys'
key = 'custom-keybindings'
# get current list
p = subprocess.run(['gsettings','get',schema,key], capture_output=True, text=True)
s = p.stdout.strip()
if s.startswith('@as '):
    s = s[4:].strip()
try:
    lst = ast.literal_eval(s)
except Exception:
    lst = []
base = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom{}/'
# find next free index
i = 0
while True:
    path = base.format(i)
    if path not in lst:
        lst.append(path)
        break
    i += 1
# set the updated list
new = '[' + ', '.join("'{}'".format(x) for x in lst) + ']'
subprocess.run(['gsettings','set',schema,key,new])
# set the name/command/binding for our new custom key
binding_base = schema + '.custom-keybinding:' + path
subprocess.run(['gsettings','set', binding_base, 'name', "'Openscript Interactive Capture'"])
cmd = f"'{PROJECT_DIR}/bin/run_interactive_capture.sh'"
subprocess.run(['gsettings','set', binding_base, 'command', cmd])
subprocess.run(['gsettings','set', binding_base, 'binding', "'<Ctrl><Super>s'" ] )
print('GNOME keybinding registered at', path)
PY
  else
    echo "Skipping GNOME keybinding registration"
  fi
else
  echo "gsettings not found; skipping GNOME keybinding registration"
fi

echo "Bootstrap complete. To run interactive capture:"
echo "  $PROJECT_DIR/bin/run_interactive_capture.sh"

echo "If you copied the .desktop file, you may need to run:"
echo "  update-desktop-database ~/.local/share/applications || true"
