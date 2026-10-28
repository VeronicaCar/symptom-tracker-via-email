"""Dark theme for the Tk window, including the Windows title bar."""

import ctypes
import sys
from tkinter import ttk

# Kimbie Dark
BG = "#221a0f"
SURFACE = "#362712"
RAISED = "#423523"
BORDER = "#5a4a37"
TEXT = "#d3af86"
BRIGHT = "#e8cfa8"
MUTED = "#b08a5c"
ACCENT = "#889b4a"
ACCENT_HOVER = "#9db15a"
SELECT = "#84613d"
ACTIVE = "#4d3d28"

# Tag and chart colors (see dayview.KIND and dayview.SERIES).
KIND_COLORS = {"water": "#8ab1b0", "food": "#f79a32", "caffeine": "#a57a4c",
               "symptom": "#dc3958", "med": "#98676a", "other": RAISED}
SERIES_COLORS = {"Sinus": "#8ab1b0", "Migraine": "#f79a32", "Dizzy": "#dc3958",
                 "Fatigue": "#e3b583", "Nausea": "#98676a", "Other": "#a57a4c"}
HEAT = ["#2c2116", "#4d5a2a", "#889b4a", "#f79a32", "#dc3958"]   # none, then 1-4+ out of 10

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
    s.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=BRIGHT)
    s.configure("Card.TFrame", background=SURFACE)
    s.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    s.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
    s.configure("CardBig.TLabel", background=SURFACE, foreground=BRIGHT, font=("Segoe UI", 16, "bold"))

    s.configure("TButton", background=RAISED, foreground=TEXT, padding=(10, 5),
                borderwidth=1, focusthickness=0)
    s.map("TButton", background=[("pressed", BORDER), ("active", ACTIVE)])
    s.configure("Accent.TButton", background=ACCENT, bordercolor=ACCENT, foreground=BG)
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
    s.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", BG)])
    s.configure("TMenubutton", background=RAISED, foreground=TEXT, padding=(10, 5),
                arrowcolor=TEXT, borderwidth=1)
    s.map("TMenubutton", background=[("active", ACTIVE)])
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
