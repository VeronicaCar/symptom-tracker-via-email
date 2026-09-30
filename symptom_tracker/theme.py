"""Dark theme for the Tk window, including the Windows title bar."""

import ctypes
import sys
from tkinter import ttk

BG = "#1e1f22"
SURFACE = "#2b2d31"
RAISED = "#383a40"
BORDER = "#45474d"
TEXT = "#e6e6e6"
MUTED = "#9a9ca3"
ACCENT = "#3d8b75"
ACCENT_HOVER = "#4aa38a"
SELECT = "#2f5f53"

FONT = ("Segoe UI", 10)


def dark_titlebar(window):
    """Ask Windows 10/11 to draw this window's title bar dark."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on),
                                                          ctypes.sizeof(on)) == 0:
                break
    except (AttributeError, OSError):
        pass


def apply(root):
    root.configure(bg=BG)
    root.option_add("*Font", FONT)
    # Dropdown lists of comboboxes are plain Tk listboxes.
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                troughcolor=BG, focuscolor=ACCENT, insertcolor=TEXT,
                selectbackground=SELECT, selectforeground=TEXT, font=FONT)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Summary.TLabel", font=("Segoe UI", 11, "bold"))

    s.configure("TButton", background=RAISED, foreground=TEXT, padding=(10, 5),
                borderwidth=1, focusthickness=0)
    s.map("TButton", background=[("pressed", BORDER), ("active", "#43454c")])
    s.configure("Accent.TButton", background=ACCENT, bordercolor=ACCENT)
    s.map("Accent.TButton", background=[("pressed", ACCENT), ("active", ACCENT_HOVER)])

    s.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, padding=4)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    s.configure("TCombobox", fieldbackground=SURFACE, background=RAISED, foreground=TEXT,
                arrowcolor=TEXT, padding=3)
    s.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
          foreground=[("readonly", TEXT)], selectbackground=[("readonly", SURFACE)],
          selectforeground=[("readonly", TEXT)], bordercolor=[("focus", ACCENT)])
    s.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=SURFACE,
                indicatorforeground=TEXT)
    s.map("TCheckbutton", background=[("active", BG)],
          indicatorbackground=[("selected", ACCENT), ("active", RAISED)])

    s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                rowheight=26, borderwidth=0)
    s.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=RAISED, foreground=TEXT, relief="flat",
                padding=(6, 4))
    s.map("Treeview.Heading", background=[("active", BORDER)])

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    s.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(14, 6),
                borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", RAISED)], foreground=[("selected", TEXT)])
    s.configure("TMenubutton", background=RAISED, foreground=TEXT, padding=(10, 5),
                arrowcolor=TEXT, borderwidth=1)
    s.map("TMenubutton", background=[("active", "#43454c")])
    s.configure("Vertical.TScrollbar", background=RAISED, troughcolor=SURFACE,
                arrowcolor=TEXT, bordercolor=SURFACE)
    s.map("Vertical.TScrollbar", background=[("active", BORDER)])
    dark_titlebar(root)


def dialog(window):
    window.configure(bg=BG)
    dark_titlebar(window)


def text_widget_options():
    return dict(bg=SURFACE, fg=TEXT, insertbackground=TEXT, selectbackground=SELECT,
                relief="flat", highlightthickness=1, highlightbackground=BORDER,
                highlightcolor=ACCENT, font=("Consolas", 10), padx=6, pady=4)


def menu_options():
    return dict(tearoff=0, bg=SURFACE, fg=TEXT, activebackground=SELECT,
                activeforeground=TEXT, bd=0)
