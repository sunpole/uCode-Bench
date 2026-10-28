"""Lightweight dark HUD palette for existing Tk; no new dependencies."""
from tkinter import ttk

COLORS = {"background": "#0b1220", "surface": "#131f32", "raised": "#21344d",
          "border": "#31445e", "text": "#edf4fc", "muted": "#a5b7ce",
          "accent": "#5ce0bd", "accent_text": "#08271e", "danger": "#f28a8a"}


def apply_dark_theme(root):
    c = COLORS
    root.configure(background=c["background"])
    root.option_add("*Menu.background", c["surface"])
    root.option_add("*Menu.foreground", c["text"])
    root.option_add("*Menu.activeBackground", c["raised"])
    root.option_add("*Menu.activeForeground", c["accent"])
    root.option_add("*Menu.disabledForeground", c["muted"])
    root.option_add("*TCombobox*Listbox.background", c["surface"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["raised"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["accent"])
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 8), background=c["background"], foreground=c["text"],
                    bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
                    troughcolor=c["surface"], focuscolor=c["accent"])
    style.configure("TFrame", background=c["background"])
    style.configure("TLabel", background=c["background"])
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Accent.TLabel", foreground=c["accent"])
    style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
    style.configure("Result.TLabel", font=("Segoe UI", 11, "bold"), foreground=c["accent"])
    style.configure("TButton", background=c["surface"], padding=(9, 3), relief="flat")
    style.map("TButton", background=[("active", c["raised"]), ("disabled", c["surface"])],
              foreground=[("disabled", c["muted"])])
    style.configure("TMenubutton", background=c["surface"], padding=(7, 3), relief="flat")
    style.map("TMenubutton", background=[("active", c["raised"])])
    style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(16, 7),
                    background=c["accent"], foreground=c["accent_text"])
    style.map("Primary.TButton", background=[("disabled", c["raised"]), ("active", "#85f0d2")],
              foreground=[("disabled", c["muted"]), ("!disabled", c["accent_text"])])
    style.configure("Danger.TButton", foreground=c["danger"])
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=c["surface"], background=c["raised"], foreground=c["text"],
                        insertcolor=c["text"], arrowsize=12)
        style.map(name, fieldbackground=[("disabled", c["background"]), ("readonly", c["surface"])],
                  foreground=[("disabled", c["muted"]), ("readonly", c["text"])])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=c["background"], foreground=c["text"])
        style.map(name, background=[("active", c["background"])],
                  foreground=[("disabled", c["muted"])], indicatorbackground=[("selected", c["accent"])])
    style.configure("TNotebook", background=c["background"], borderwidth=0, tabmargins=(0, 0, 0, 2))
    style.configure("TNotebook.Tab", background=c["surface"], padding=(12, 3))
    style.map("TNotebook.Tab", background=[("selected", c["raised"])],
              foreground=[("selected", c["accent"])])
    style.configure("Horizontal.TProgressbar", background=c["accent"], troughcolor=c["surface"],
                    borderwidth=0, thickness=8)
    return style
