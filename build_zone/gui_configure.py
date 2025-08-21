import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import yaml
import os
import subprocess
import sys
from PIL import Image, ImageTk

VARS_PATH = os.path.join(os.path.dirname(__file__), "variables.yaml")


def safe_call(cmd):
    try:
        return subprocess.check_output(cmd).decode('utf-8')
    except Exception:
        return ''


class ConfigWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OpenScript - Configure Variables")
        self.geometry("800x480")
        self.resizable(True, True)

        self.vars = {}
        self.load_vars()

        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(top, text="Variables (from interactive capture)", font=("Arial", 12)).pack(side=tk.LEFT)
        tk.Button(top, text="Add", command=self.add_var).pack(side=tk.RIGHT)
        tk.Button(top, text="Select target window", command=self.select_window).pack(side=tk.RIGHT, padx=6)

        body = tk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = tk.Frame(body)
        right = tk.Frame(body, width=300)
        body.add(left, stretch='always')
        body.add(right)

        # Tree on left
        self.tree = ttk.Treeview(left, columns=("value",), show="headings")
        self.tree.heading("value", text="Value")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind('<Double-1>', self.edit_selected)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)

        btns = tk.Frame(left)
        btns.pack(fill=tk.X)
        tk.Button(btns, text="Rename", command=self.rename_var).pack(side=tk.LEFT, padx=4, pady=4)
        tk.Button(btns, text="Delete", command=self.delete_var).pack(side=tk.LEFT, padx=4, pady=4)

        # Right: preview area
        tk.Label(right, text="Preview", font=("Arial", 12)).pack()
        self.preview_label = tk.Label(right, text="No preview", width=40, height=20, bg='#eee')
        self.preview_label.pack(padx=8, pady=8)
        tk.Button(right, text="Preview selected (image/window)", command=self.preview_selected).pack(pady=4)

        bottom = tk.Frame(self)
        bottom.pack(fill=tk.X, padx=8, pady=8)
        tk.Button(bottom, text="Save", command=self.save_vars).pack(side=tk.RIGHT)
        tk.Button(bottom, text="Close", command=self.quit).pack(side=tk.RIGHT, padx=6)

        self.img_cache = None
        self.refresh_tree()

    def load_vars(self):
        if os.path.exists(VARS_PATH):
            with open(VARS_PATH, 'r') as f:
                try:
                    self.vars = yaml.safe_load(f) or {}
                except Exception:
                    self.vars = {}
        else:
            self.vars = {}

    def refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for k, v in (self.vars or {}).items():
            self.tree.insert('', 'end', iid=k, values=(f"{v}"))

    def validate_name(self, name):
        if not name:
            messagebox.showerror("Invalid name", "Variable name cannot be empty")
            return False
        if ' ' in name:
            messagebox.showerror("Invalid name", "Variable name cannot contain spaces")
            return False
        return True

    def add_var(self):
        name = simpledialog.askstring("Variable name", "Enter variable name:", parent=self)
        if not name:
            return
        if not self.validate_name(name):
            return
        if name in self.vars:
            messagebox.showerror("Exists", "Variable already exists")
            return
        value = simpledialog.askstring("Value", f"Enter value for {name}:", parent=self)
        self.vars[name] = value
        self.refresh_tree()

    def edit_selected(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        cur = self.vars.get(key, '')
        new = simpledialog.askstring("Edit value", f"Value for {key}:", initialvalue=cur, parent=self)
        if new is not None:
            self.vars[key] = new
            self.refresh_tree()

    def on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self.preview_label.config(text="No preview", image='')
            return
        key = sel[0]
        val = self.vars.get(key, '')
        # show thumbnail if image file
        if isinstance(val, str) and os.path.exists(val) and val.lower().endswith(('.png', '.jpg', '.jpeg')):
            try:
                img = Image.open(val)
                img.thumbnail((320, 240))
                self.img_cache = ImageTk.PhotoImage(img)
                self.preview_label.config(image=self.img_cache, text='')
                return
            except Exception:
                pass
        # otherwise clear preview text
        self.preview_label.config(text=str(val), image='')

    def rename_var(self):
        sel = self.tree.selection()
        if not sel:
            return
        old = sel[0]
        new = simpledialog.askstring("Rename variable", "New name:", initialvalue=old, parent=self)
        if not new or new == old:
            return
        if not self.validate_name(new):
            return
        if new in self.vars:
            messagebox.showerror("Exists", "A variable with that name already exists")
            return
        self.vars[new] = self.vars.pop(old)
        # update tree iid
        self.refresh_tree()
        try:
            self.tree.selection_set(new)
        except Exception:
            pass

    def delete_var(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        if messagebox.askyesno("Delete", f"Delete variable {key}?"):
            self.vars.pop(key, None)
            self.refresh_tree()

    def save_vars(self):
        with open(VARS_PATH, 'w') as f:
            yaml.safe_dump(self.vars, f)
        messagebox.showinfo("Saved", f"Variables saved to {VARS_PATH}")

    def select_window(self):
        # Try to list windows using wmctrl first, fall back to a simple dialog
        try:
            out = safe_call(["wmctrl", "-lG"]).strip()
            lines = [l for l in out.splitlines() if l.strip()]
            choices = []
            for l in lines:
                parts = l.split(None, 6)
                # wmctrl -lG: id desktop x y w h host title
                if len(parts) >= 7:
                    wid, desktop, x, y, w, h, rest = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
                    title = rest
                    choices.append((wid, int(x), int(y), int(w), int(h), title))
            if not choices:
                raise RuntimeError("No windows found")
            sel = WindowSelectDialog(self, choices).result
            if sel:
                # sel is tuple (wid,x,y,w,h,title)
                wid, x, y, w, h, title = sel
                self.vars['target_window'] = wid
                # store geometry for preview
                self.vars['target_window_geometry'] = f"{x},{y},{w},{h}"
                self.refresh_tree()
        except Exception:
            # fallback: ask user to paste a window title or id
            val = simpledialog.askstring("Target window", "Enter window title or id:", parent=self)
            if val:
                self.vars['target_window'] = val
                self.refresh_tree()

    def preview_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        val = self.vars.get(key, '')
        # If var is an image path, open a larger preview
        if isinstance(val, str) and os.path.exists(val) and val.lower().endswith(('.png', '.jpg', '.jpeg')):
            try:
                img = Image.open(val)
                img.thumbnail((800, 600))
                top = tk.Toplevel(self)
                top.title(f"Preview: {key}")
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(top, image=photo)
                lbl.image = photo
                lbl.pack()
                return
            except Exception as e:
                messagebox.showerror("Preview error", str(e))
                return
        # If var is target window, try to show a screenshot of that geometry
        geom = self.vars.get('target_window_geometry')
        if geom:
            try:
                x, y, w, h = map(int, geom.split(','))
                # take screenshot of region using pyautogui if available
                try:
                    import pyautogui
                    img = pyautogui.screenshot(region=(x, y, w, h))
                    img = img.resize((min(800, w), min(600, h)))
                    top = tk.Toplevel(self)
                    top.title("Window preview")
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(top, image=photo)
                    lbl.image = photo
                    lbl.pack()
                    return
                except Exception:
                    messagebox.showinfo("Preview", "pyautogui screenshot not available on this system")
                    return
            except Exception:
                messagebox.showerror("Preview error", "Invalid stored geometry")
                return
        messagebox.showinfo("Preview", "No preview available for selected variable")


class WindowSelectDialog(simpledialog.Dialog):
    def __init__(self, parent, choices):
        self.choices = choices
        self.result = None
        super().__init__(parent, title="Select window")

    def body(self, master):
        tk.Label(master, text="Select a window:").pack()
        self.lb = tk.Listbox(master, width=120)
        for wid, x, y, w, h, title in self.choices:
            self.lb.insert(tk.END, f"{wid} - {title} ({x},{y} {w}x{h})")
        self.lb.pack()

    def apply(self):
        sel = self.lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self.result = self.choices[idx]


if __name__ == '__main__':
    app = ConfigWindow()
    app.mainloop()
