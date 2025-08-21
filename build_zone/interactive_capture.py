#!/usr/bin/env python3
"""Interactive capture helper.

    Listen for a hotkey (Ctrl+Meta+S by default) to start a screen selection.
After selection prompt for a name, save the cropped image to build_zone/data/<name>.png
and write/update build_zone/variables.yaml with the mapping {name: path} so runner
and automations can reference saved templates by variable name.

Usage:
  python build_zone/interactive_capture.py

If running in an environment where global hotkeys are not available, press Enter
when prompted to trigger a capture.
"""
from pathlib import Path
import os
import sys
import threading
import time
import yaml

try:
    from pynput import keyboard
except Exception:
    keyboard = None

import pyautogui
from PIL import Image
import numpy as np
import subprocess

# try OpenCV selectROI if available
try:
    import cv2
    HAVE_CV2 = True
except Exception:
    cv2 = None
    HAVE_CV2 = False

# Tkinter fallback for selection
try:
    import tkinter as tk
    from PIL import ImageTk
    HAVE_TK = True
except Exception:
    HAVE_TK = False

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
VARS_PATH = ROOT / "variables.yaml"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def gui_notify(title: str, message: str):
    """Try to show a desktop notification or Tk messagebox as a fallback."""
    # try notify-send
    try:
        subprocess.run(["notify-send", title, message], check=False)
        return
    except Exception:
        pass

    # Tk fallback
    if HAVE_TK:
        try:
            import tkinter.messagebox as messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(title, message)
            root.destroy()
            return
        except Exception:
            pass


def gui_input(prompt: str, title: str = "Openscript") -> str | None:
    """Return a string from GUI prompt if no TTY is available, else use input()."""
    # If we have a tty, prefer console input
    try:
        if sys.stdin and sys.stdin.isatty():
            return input(prompt)
    except Exception:
        pass

    # Tkinter simple dialog
    if HAVE_TK:
        try:
            import tkinter.simpledialog as simpledialog
            root = tk.Tk()
            root.withdraw()
            res = simpledialog.askstring(title, prompt)
            root.destroy()
            return res
        except Exception:
            pass

    # zenity fallback
    try:
        p = subprocess.run(["zenity", "--entry", "--title", title, "--text", prompt], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:
        pass

    return None


class StatusWindow:
    """Small non-blocking Tk status window used when no console is present."""
    def __init__(self, title: str = "Openscript"):
        self._active = False
        if not HAVE_TK:
            return
        try:
            self._root = tk.Tk()
            self._root.title(title)
            # small window
            try:
                self._root.geometry("320x80")
            except Exception:
                pass
            self._root.attributes("-topmost", True)
            self._label = tk.Label(self._root, text="", anchor="w", justify="left", padx=8, pady=8)
            self._label.pack(fill="both", expand=True)
            # prevent user from closing accidentally
            try:
                self._root.protocol("WM_DELETE_WINDOW", lambda: None)
            except Exception:
                pass
            # run mainloop in background thread
            self._thread = threading.Thread(target=self._root.mainloop, daemon=True)
            self._thread.start()
            self._active = True
        except Exception:
            self._active = False

    def update(self, text: str):
        if not self._active:
            return
        try:
            self._root.after(0, lambda: self._label.config(text=text))
        except Exception:
            pass

    def close(self):
        if not self._active:
            return
        try:
            self._root.after(0, lambda: (self._root.destroy()))
        except Exception:
            pass
        self._active = False


def save_variable(name: str, path: str):
    vars_map = {}
    if VARS_PATH.exists():
        try:
            vars_map = yaml.safe_load(VARS_PATH.read_text()) or {}
        except Exception:
            vars_map = {}
    vars_map[name] = str(path)
    VARS_PATH.write_text(yaml.safe_dump(vars_map))


def tk_select_bbox(pil_img: Image.Image):
    """Show a Tk window to select a rectangle and return (x, y, w, h)."""
    if not HAVE_TK:
        return None

    root = tk.Tk()
    root.title("Select area and press Enter")

    w, h = pil_img.size
    canvas = tk.Canvas(root, width=w, height=h)
    canvas.pack()
    tk_img = ImageTk.PhotoImage(pil_img)
    canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)

    rect = None
    start_x = start_y = 0
    bbox = [0, 0, 0, 0]

    def on_button_press(event):
        nonlocal start_x, start_y, rect
        start_x = event.x
        start_y = event.y
        rect = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

    def on_move(event):
        nonlocal rect
        if rect:
            canvas.coords(rect, start_x, start_y, event.x, event.y)

    def on_button_release(event):
        nonlocal bbox
        x0 = min(start_x, event.x)
        y0 = min(start_y, event.y)
        x1 = max(start_x, event.x)
        y1 = max(start_y, event.y)
        bbox = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]

    def on_key(event):
        # Enter closes
        if event.keysym == 'Return':
            root.quit()

    canvas.bind("<ButtonPress-1>", on_button_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_button_release)
    root.bind('<Key>', on_key)

    root.mainloop()
    root.destroy()
    return tuple(bbox) if bbox and bbox[2] > 0 and bbox[3] > 0 else None


def select_area(image: np.ndarray):
    """Return bbox (x,y,w,h) for selected area. Try cv2.selectROI then Tk fallback."""
    if HAVE_CV2 and hasattr(cv2, 'selectROI'):
        try:
            b = cv2.selectROI("Select area", image, showCrosshair=True, fromCenter=False)
            cv2.destroyWindow("Select area")
            x, y, w, h = b
            if w > 0 and h > 0:
                return (int(x), int(y), int(w), int(h))
        except Exception:
            pass

    # Tk fallback
    if HAVE_TK:
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if HAVE_CV2 else Image.fromarray(image))
        return tk_select_bbox(pil)

    return None


def capture_crop_and_save(bbox, out_path: Path, img=None):
    """Crop screenshot by bbox and save to out_path."""
    if img is None:
        ss = pyautogui.screenshot()
        arr = np.array(ss)
        img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if HAVE_CV2 else arr

    x, y, w, h = bbox
    if HAVE_CV2:
        crop = img[y:y + h, x:x + w]
        cv2.imwrite(str(out_path), crop)
    else:
        pil = Image.fromarray(img)
        crop = pil.crop((x, y, x + w, y + h))
        crop.save(str(out_path))


def on_hotkey_triggered(name=None):
    # take full screen screenshot
    ss = pyautogui.screenshot()
    arr = np.array(ss)
    if HAVE_CV2:
        img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    else:
        img = arr

    # show a status window if no tty
    status = None
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            status = StatusWindow()
            status.update('Select area with mouse, then press Enter')
    except Exception:
        status = None

    bbox = select_area(img)
    if not bbox:
        if status:
            status.update('No area selected')
            status.close()
        print("No area selected")
        return

    if not name:
        name = gui_input("Name for selection (no spaces): ")
        if name is None:
            if status:
                status.update('No name provided; aborting')
                status.close()
            print("No name provided; aborting")
            return
        name = name.strip().replace(" ", "_")
    if not name:
        print("No name provided; aborting")
        return

    out_path = DATA_DIR / f"{name}.png"
    capture_crop_and_save(bbox, out_path, img=img)
    save_variable(name, out_path)
    # notify user via GUI when no console is available
    if status:
        status.update(f"Saved selection '{name}' -> {out_path}")
        # keep it visible for a moment
        time.sleep(0.5)
        status.close()
    try:
        gui_notify("Openscript", f"Saved selection '{name}' -> {out_path}")
    except Exception:
        pass
    print(f"Saved selection '{name}' -> {out_path}")


def listen_for_hotkey(combo=(keyboard.Key.ctrl, keyboard.Key.cmd, keyboard.KeyCode.from_char('s')) if keyboard else None):
    """Listen for the specified combo. If pynput not installed, ask user to press Enter."""
    if keyboard is None:
        input("Press Enter to start selection...")
        on_hotkey_triggered()
        return

    pressed = set()

    def on_press(key):
        try:
            pressed.add(key)
            # check combo
            if all(k in pressed for k in combo):
                print("Hotkey pressed; starting selection...")
                on_hotkey_triggered()
        except Exception:
            pass

    def on_release(key):
        try:
            if key in pressed:
                pressed.remove(key)
        except Exception:
            pass

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        print("Listening for hotkey (Ctrl+Meta+S) — press it to capture selection. Ctrl+C to quit.")
        listener.join()


if __name__ == '__main__':
    try:
        listen_for_hotkey()
    except KeyboardInterrupt:
        print("Exiting")
        sys.exit(0)
