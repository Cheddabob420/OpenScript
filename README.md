OpenCV + Selenium automation runner

This project provides tools to capture templates from your screen, detect them later, and drive actions (native clicks, notifications, commands) based on matches.

Highlights
- Interactive capture helper: `build_zone/interactive_capture.py` — press Ctrl+Shift+S to select an area, give it a name, and the crop is saved to `build_zone/data/<name>.png` and registered in `build_zone/variables.yaml`.
- Automation runner: `build_zone/automation_runner.py` — YAML-driven runner supporting `detect_image`, `click_image`, `notify`, `run_command`, and `reload_vars` actions.
- Jinja2 templating (if available) in action params and messages; fallback simple replacement is used otherwise.

Quickstart

1. Create and activate a venv (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Capture a template interactively:

```bash
python build_zone/interactive_capture.py
```

Press Ctrl+Shift+S and draw a box around the element you want to save (e.g. the Google logo). Name it "google_logo" (no spaces). The file will be saved to `build_zone/data/google_logo.png` and `build_zone/variables.yaml` will be updated.

4. Example automation (see `config.automation.example.yaml`):

```yaml
# Example
target:
	type: window_title
	value: "Google"
actions:
	- type: reload_vars
	- type: detect_image
		params:
			template_path: "{{ google_logo }}"
	- type: click_image
		params:
			template_path: "{{ google_logo }}"
			native_click: true
```

Notes
- To reload variables captured during a running session, include the `reload_vars` action; it reads `build_zone/variables.yaml` and updates the runner's `vars` for subsequent actions.
- Templating: if `jinja2` is installed the runner will render action params and messages with Jinja2 (you get `vars`, `last_match_score`, `attempts` in the template context). Otherwise a simple `{{ name }}` string replacement is used.
- Native clicks use `pyautogui` and require a desktop session. On Linux `pygetwindow` is used for window geometry when available, otherwise the runner falls back to `xdotool` or full-screen origin.



Release
-------

A minimal source release and a full release are available in the repository root as:

- `openscript-minimal.tar.gz` (source + scripts, small)
- `openscript-minimal.zip`
- `openscript-release.tar.gz` (full packaged runtime — large)
- `openscript-release.zip`


