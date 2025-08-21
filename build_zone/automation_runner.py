#!/usr/bin/env python3
"""Automation runner: execute `config.automation.template.yaml`-style files.

Usage:
  python build_zone/automation_runner.py --config myautomation.yaml [--dry-run] [--headless]

This runner supports a small set of actions: detect_image, notify, run_command.
It dynamically loads `build_zone/main.py` to reuse screenshot + matching helpers.
"""
import argparse
import importlib.util
import time
import subprocess
from pathlib import Path
import yaml
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional, Any
import sys
import pyautogui
try:
    import pygetwindow as gw
except Exception:
    gw = None
    # we'll try xdotool/wmctrl fallback later

import shlex
from subprocess import PIPE
import random
try:
    from jinja2 import Template, Environment, StrictUndefined
    HAVE_JINJA = True
except Exception:
    HAVE_JINJA = False


def get_window_bbox_by_xdotool(title: str):
    """Try to find window geometry using xdotool (Linux). Returns (left, top, width, height) or None."""
    try:
        # search window ids
        cmd = f"xdotool search --name {shlex.quote(title)}"
        p = subprocess.run(cmd, shell=True, stdout=PIPE, stderr=PIPE, text=True)
        if p.returncode != 0 or not p.stdout.strip():
            return None
        win_id = p.stdout.strip().splitlines()[0]
        # get geometry
        cmd2 = f"xdotool getwindowgeometry --shell {shlex.quote(win_id)}"
        p2 = subprocess.run(cmd2, shell=True, stdout=PIPE, stderr=PIPE, text=True)
        if p2.returncode != 0:
            return None
        geom = {}
        for line in p2.stdout.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                geom[k.strip()] = int(v.strip())
        left = geom.get('X')
        top = geom.get('Y')
        width = geom.get('WIDTH')
        height = geom.get('HEIGHT')
        if None in (left, top, width, height):
            return None
        return (left, top, width, height)
    except Exception:
        return None


def load_main_module():
    main_path = Path(__file__).resolve().parent / "main.py"
    spec = importlib.util.spec_from_file_location("build_zone_main", str(main_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def eval_cond(expr: str, ctx: dict) -> bool:
    if not expr:
        return False
    expr = expr.strip()
    if expr.lower() == "true":
        return True
    try:
        # safe-ish eval: no builtins, only ctx available
        return bool(eval(expr, {}, ctx))
    except Exception:
        return False


class TargetModel(BaseModel):
    type: str
    value: str
    capture_method: Optional[str] = "screenshot"


class PollingModel(BaseModel):
    interval_seconds: int = 10
    max_attempts: int = 0
    timeout_seconds: Optional[int] = None


class ActionModel(BaseModel):
    name: str
    type: str
    params: Optional[dict] = Field(default_factory=dict)
    when: Optional[str] = "true"


class ExitActionModel(BaseModel):
    condition: str
    action: Optional[dict]


class AutomationConfig(BaseModel):
    id: Optional[str]
    description: Optional[str]
    target: TargetModel
    polling: Optional[PollingModel] = Field(default_factory=PollingModel)
    actions: List[ActionModel]
    exit: Optional[dict] = None


class AutomationRunner:
    def __init__(self, cfg_path: Path, dry_run: bool = False, headless: bool = False):
        self.cfg_path = Path(cfg_path)
        self.cfg = yaml.safe_load(self.cfg_path.read_text())
        self.dry_run = dry_run
        self.headless = headless or self.cfg.get("headless", False)
        self.mod = load_main_module()

        # state
        self.attempts = 0
        self.start_time = time.time()
        self.last_match_score = 0.0
        self.target_found = False
        # persistent browser driver (None until created)
        self.driver = None
        # load variables (from interactive_capture)
        self.variables = {}
        vars_path = Path(__file__).resolve().parent / "variables.yaml"
        if vars_path.exists():
            try:
                self.variables = yaml.safe_load(vars_path.read_text()) or {}
            except Exception:
                self.variables = {}
        # jinja environment
        if HAVE_JINJA:
            self.jinja_env = Environment(undefined=StrictUndefined)
        else:
            self.jinja_env = None

    def validate(self):
        try:
            self.typed = AutomationConfig(**self.cfg)
        except ValidationError as e:
            raise ValueError(f"config validation failed: {e}")

    def dry(self):
        print("Dry run: planned automation steps")
        print(yaml.dump(self.cfg))

    def run(self):
        polling = self.cfg.get("polling", {})
        interval = polling.get("interval_seconds", 10)
        max_attempts = polling.get("max_attempts", 0) or 0

        while True:
            self.attempts += 1
            elapsed = time.time() - self.start_time
            # target type
            target = self.cfg.get("target", {})
            ttype = target.get("type", "url")

            # capture / detection
            for action in self.cfg.get("actions", []):
                when = action.get("when", "true")
                ctx = {
                    "last_match_score": self.last_match_score,
                    "attempts": self.attempts,
                    "elapsed_seconds": elapsed,
                    "target_found": self.target_found,
                    "vars": self.variables,
                }
                if not eval_cond(when, ctx):
                    continue

                print(f"Executing action: {action.get('name')} (type={action.get('type')})")
                if self.dry_run:
                    continue

                # render params using Jinja2 if available, else fallback to simple replacement
                def render_param(v):
                    if not isinstance(v, str):
                        return v
                    if HAVE_JINJA and self.jinja_env:
                        try:
                            tpl = self.jinja_env.from_string(v)
                            ctx = {"vars": self.variables, "last_match_score": self.last_match_score, "attempts": self.attempts}
                            return tpl.render(**ctx)
                        except Exception:
                            return v
                    # fallback simple replacement
                    if "{{" in v and "}}" in v:
                        for k, val in self.variables.items():
                            v = v.replace(f"{{{{ {k} }}}}", str(val))
                            v = v.replace(f"{{{{{k}}}}}", str(val))
                    return v

                if isinstance(params, dict):
                    for pk, pv in list(params.items()):
                        params[pk] = render_param(pv)

                t = action.get("type")
                params = action.get("params", {})

                if t == "detect_image":
                    # Detection supports browser screenshots (default) and desktop/window captures
                    target = self.cfg.get("target", {})
                    ttype = target.get("type", "url")
                    img = None
                    # prefer persistent driver
                    try:
                        if ttype in ("url", "selector"):
                            url = target.get("value", "https://www.google.com")
                            driver = self.get_driver(url)
                            img = self.mod.cv2.imread(str(self.mod.Path(self.cfg.get("screenshot", "build_zone/data/google.png"))))
                        elif ttype in ("window_title", "process_name"):
                            # capture window by title
                            title = target.get("value")
                            bbox = None
                            if gw:
                                for w in gw.getAllWindows():
                                    if title.lower() in (w.title or "").lower():
                                        bbox = (w.left, w.top, w.width, w.height)
                                        break

                            if bbox is None:
                                # try xdotool fallback on Linux
                                bbox = get_window_bbox_by_xdotool(title)

                            if bbox:
                                ss = pyautogui.screenshot(region=bbox)
                                img = self.mod.cv2.cvtColor(self.mod.np.array(ss), self.mod.cv2.COLOR_RGB2BGR)
                            else:
                                print(f"Window with title containing '{title}' not found; falling back to full-screen capture")
                                ss = pyautogui.screenshot()
                                img = self.mod.cv2.cvtColor(self.mod.np.array(ss), self.mod.cv2.COLOR_RGB2BGR)
                        else:
                            print(f"Unknown target type for detect_image: {ttype}")

                        template_path = Path(params.get("template_path"))
                        template = self.mod.cv2.imread(str(template_path))
                        if img is None or template is None:
                            print("Failed to read screenshot or template for detection")
                            self.last_match_score = 0.0
                            self.target_found = False
                        else:
                            scales = params.get("scales")
                            best_val, best_loc, (w, h) = self.mod.multi_scale_template_match(img, template, scales=scales)
                            print(f"Detected score: {best_val}")
                            self.last_match_score = float(best_val)
                            self.target_found = best_val >= params.get("threshold", 0.78)
                            if params.get("save_detected_annotated") and best_loc and self.target_found:
                                top_left = best_loc
                                bottom_right = (top_left[0] + w, top_left[1] + h)
                                annotated = img.copy()
                                self.mod.cv2.rectangle(annotated, top_left, bottom_right, (0, 0, 255), 3)
                                annotated_path = params.get("annotated_path") or self.cfg.get("annotated")
                                if annotated_path:
                                    self.mod.cv2.imwrite(str(annotated_path), annotated)
                    except Exception as e:
                        print(f"detect_image failed: {e}")
                    # do not quit driver here; persistent driver will be cleaned up after actions

                elif t == "notify":
                    title = params.get("title", "Automation")
                    message = params.get("message", "")
                    # simple template replacement
                    message = message.replace("{{ last_match_score }}", str(self.last_match_score))
                    try:
                        self.mod.notify_desktop(title, message)
                    except Exception as e:
                        print(f"notify failed: {e}")

                elif t == "run_command":
                    cmd = params.get("command")
                    if not cmd:
                        continue
                    # if command looks like JS alert and a driver exists, run in browser
                    if cmd.strip().startswith("alert("):
                        url = self.cfg.get("target", {}).get("value", "https://www.google.com")
                        d = self.get_driver(url)
                        try:
                            try:
                                d.execute_script(cmd)
                                time.sleep(0.5)
                            except Exception as e:
                                print(f"failed to exec script: {e}")
                        except Exception:
                            pass
                    else:
                        try:
                            subprocess.run(cmd, shell=True)
                        except Exception as e:
                            print(f"run_command failed: {e}")

                elif t == "click_selector":
                    selector = params.get("selector")
                    if not selector:
                        print("click_selector missing selector param")
                        continue
                    url = self.cfg.get("target", {}).get("value", "https://www.google.com")
                    d = self.get_driver(url)
                    try:
                        try:
                            el = d.find_element(self.mod.By.CSS_SELECTOR, selector)
                            el.click()
                        except Exception as e:
                            print(f"click_selector failed: {e}")
                    except Exception:
                        pass

                elif t == "keystroke":
                    # simple keystroke emmulation using Selenium send_keys to active element or selector
                    keys = params.get("keys")
                    selector = params.get("selector")
                    url = self.cfg.get("target", {}).get("value", "https://www.google.com")
                    d = self.get_driver(url)
                    try:
                        try:
                            if selector:
                                el = d.find_element(self.mod.By.CSS_SELECTOR, selector)
                                el.send_keys(keys)
                            else:
                                d.switch_to.active_element.send_keys(keys)
                        except Exception as e:
                            print(f"keystroke failed: {e}")
                    except Exception:
                        pass

                elif t == "click_image":
                    # detect the image first
                    url = self.cfg.get("target", {}).get("value", "https://www.google.com")
                    # prefer persistent driver
                    local_driver = self.get_driver(url) if ttype in ("url", "selector") else None
                    try:
                        # when using a browser driver, rely on saved screenshot path
                        if local_driver is not None:
                            img = self.mod.cv2.imread(str(self.mod.Path(self.cfg.get("screenshot", "build_zone/data/google.png"))))
                        else:
                            # desktop capture (full screen or window bbox handled earlier in detect)
                            img = None
                        template_path = Path(params.get("template_path"))
                        template = self.mod.cv2.imread(str(template_path))
                        if img is None or template is None:
                            print("Failed to read screenshot or template for click_image")
                            continue

                        scales = params.get("scales")
                        best_val, best_loc, (w, h) = self.mod.multi_scale_template_match(img, template, scales=scales)
                        print(f"click_image detected score: {best_val}")
                        if best_loc is None:
                            continue

                        # compute click target; default is center
                        cx = best_loc[0] + w / 2
                        cy = best_loc[1] + h / 2

                        # optional expansion box
                        click_w = params.get("click_width")
                        click_h = params.get("click_height")
                        if click_w and click_h:
                            # center of expanded box
                            cx = best_loc[0] + w / 2
                            cy = best_loc[1] + h / 2
                            # compute expanded box coords (no randomness for now)
                            x0 = cx - float(click_w) / 2
                            y0 = cy - float(click_h) / 2
                            x1 = cx + float(click_w) / 2
                            y1 = cy + float(click_h) / 2
                            # clamp
                            cx = max(0, min(img.shape[1] - 1, (x0 + x1) / 2))
                            cy = max(0, min(img.shape[0] - 1, (y0 + y1) / 2))

                            # optional randomization inside expanded box
                            if params.get("randomize", False):
                                rx = random.uniform(x0, x1)
                                ry = random.uniform(y0, y1)
                                cx = max(0, min(img.shape[1] - 1, rx))
                                cy = max(0, min(img.shape[0] - 1, ry))

                        native_click = params.get("native_click", False)

                        if native_click and ttype in ("window_title", "process_name"):
                            # perform native click on screen coords
                            # we already support window bbox capture during detect_image; try to locate same window
                            title = target.get("value")
                            bbox = None
                            if gw:
                                for w in gw.getAllWindows():
                                    if title.lower() in (w.title or "").lower():
                                        bbox = (w.left, w.top, w.width, w.height)
                                        break
                            if bbox is None:
                                bbox = get_window_bbox_by_xdotool(title)
                            if bbox is None:
                                # fallback to full screen origin
                                left, top = 0, 0
                            else:
                                left, top = bbox[0], bbox[1]

                            screen_x = int(left + cx)
                            screen_y = int(top + cy)
                            try:
                                pyautogui.click(screen_x, screen_y)
                            except Exception as e:
                                print(f"native pyautogui.click failed: {e}")

                        else:
                            # use browser click via elementFromPoint; prefer persistent driver
                            use_driver = local_driver or self.driver
                            if use_driver is None:
                                print("No browser driver available to perform click_image")
                            else:
                                try:
                                    dpr = float(use_driver.execute_script('return window.devicePixelRatio || 1'))
                                except Exception:
                                    dpr = 1.0
                                client_x = int(cx / dpr)
                                client_y = int(cy / dpr)
                                try:
                                    use_driver.execute_script('window.scrollTo(0, arguments[0] - 100);', client_y)
                                except Exception:
                                    pass
                                try:
                                    use_driver.execute_script(
                                        "var el = document.elementFromPoint(arguments[0], arguments[1]); if(el){ el.click(); return true;} return false;",
                                        client_x,
                                        client_y,
                                    )
                                except Exception as e:
                                    print(f"click_image JS click failed: {e}")
                    finally:
                        # do not quit persistent driver here; if a temporary driver was created separately handle it in get_driver
                        pass

                elif t == "reload_vars":
                    # reload variables from variables.yaml
                    vars_path = Path(__file__).resolve().parent / "variables.yaml"
                    if vars_path.exists():
                        try:
                            self.variables = yaml.safe_load(vars_path.read_text()) or {}
                            print("variables reloaded")
                        except Exception as e:
                            print(f"reload_vars failed: {e}")
                    else:
                        print("variables.yaml not found")

                else:
                    print(f"unknown action type: {t}")

            # check exit and loop; persistent driver remains open across loops

            # Check exit on success
            exit_cfg = self.cfg.get("exit", {})
            on_success = exit_cfg.get("on_success")
            if on_success:
                if eval_cond(on_success.get("condition", "false"), {"last_match_score": self.last_match_score, "attempts": self.attempts}):
                    act = on_success.get("action")
                    if act and act.get("type") == "notify":
                        params = act.get("params", {})
                        self.mod.notify_desktop(params.get("title", "Finished"), params.get("message", ""))
                    print("Exit condition (success) met; stopping")
                    return

            # timeout condition
            if max_attempts and self.attempts >= max_attempts:
                on_timeout = exit_cfg.get("on_timeout")
                if on_timeout and eval_cond(on_timeout.get("condition", "false"), {"attempts": self.attempts}):
                    act = on_timeout.get("action")
                    if act and act.get("type") == "notify":
                        params = act.get("params", {})
                        self.mod.notify_desktop(params.get("title", "Timeout"), params.get("message", ""))
                    print("Exit condition (timeout) met; stopping")
                    return

            time.sleep(interval)

        # cleanup persistent driver if present
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

    def get_driver(self, url: str = None):
        """Return a persistent Selenium driver for web targets, creating it if necessary."""
        if self.driver:
            return self.driver
        try:
            target = self.cfg.get("target", {})
            ttype = target.get("type", "url")
            if ttype in ("url", "selector"):
                url = url or target.get("value", "https://www.google.com")
                self.driver = self.mod.open_google_and_screenshot(url=url, headless=self.headless)
                return self.driver
        except Exception as e:
            print(f"failed to create persistent driver: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    runner = AutomationRunner(Path(args.config), dry_run=args.dry_run, headless=args.headless)
    try:
        runner.validate()
    except Exception as e:
        print(f"config validation failed: {e}")
        sys.exit(2)

    if args.dry_run:
        runner.dry()
    else:
        runner.run()


if __name__ == "__main__":
    main()
