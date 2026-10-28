"""The Journal and Charts tabs of the main window."""

import datetime as dt
import tkinter as tk
from tkinter import ttk

from . import theme
from .dayview import day_view, join_notes

FONT = "Segoe UI"


def _day_title(day):
    return day.strftime("%A, %B ") + str(day.day)


class JournalTab(ttk.Frame):
    """A day list on the left; the chosen day reads like a diary page on the right."""

    def __init__(self, master, on_pick_day):
        super().__init__(master, padding=(0, 6, 0, 0))
        self.on_pick_day = on_pick_day
        self._days = []

        left = ttk.Frame(self, style="Card.TFrame", padding=(8, 8))
        left.pack(side="left", fill="y")
        ttk.Label(left, text="DAYS", style="CardMuted.TLabel").pack(anchor="w", padx=4, pady=(0, 4))
        self.day_list = tk.Listbox(left, width=32, activestyle="none", exportselection=False,
                                   bg=theme.SURFACE, fg=theme.TEXT, bd=0, highlightthickness=0,
                                   selectbackground=theme.SELECT, selectforeground=theme.BRIGHT,
                                   font=(FONT, 10))
        self.day_list.pack(fill="y", expand=True)
        self.day_list.bind("<<ListboxSelect>>", self._picked)

        right = ttk.Frame(self, padding=(20, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        self.title = ttk.Label(right, style="Title.TLabel", font=(FONT, 18, "bold"))
        self.title.pack(anchor="w")
        self.chips = tk.Frame(right, bg=theme.BG)
        self.chips.pack(anchor="w", fill="x", pady=(6, 8))

        body = ttk.Frame(right)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", bg=theme.BG, fg=theme.BRIGHT, bd=0,
                            highlightthickness=0, font=(FONT, 11), padx=4, pady=4,
                            spacing1=2, spacing3=2, cursor="arrow", takefocus=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # Time in a left gutter; wrapped lines of a note line up after it.
        self.text.tag_configure("time", foreground=theme.MUTED, font=(FONT, 10))
        self.text.tag_configure("entry", lmargin1=0, lmargin2=86, tabs=(86,), spacing1=10)
        self.text.tag_configure("gap", font=(FONT, 4))
        for kind, color in theme.KIND_COLORS.items():
            fg = theme.BRIGHT if kind == "other" else theme.BG
            self.text.tag_configure(kind, background=color, foreground=fg, font=(FONT, 9, "bold"))
        self.text.tag_configure("empty", foreground=theme.MUTED)

    def _picked(self, _=None):
        sel = self.day_list.curselection()
        if sel and sel[0] < len(self._days):
            self.on_pick_day(self._days[sel[0]][0])

    def show_days(self, days, selected):
        """days: [(date, entry count, blurb)], newest first."""
        if days != self._days:
            self._days = days
            self.day_list.delete(0, "end")
            for day, count, blurb in days:
                label = day.strftime("%a %b ") + str(day.day)
                self.day_list.insert("end", f"  {label:<11} {count:>3}   {blurb}")
        for i, (day, _, _) in enumerate(days):
            if day == selected:
                self.day_list.selection_clear(0, "end")
                self.day_list.selection_set(i)
                self.day_list.see(i)

    def show_day(self, day, rows, chips):
        """rows: that day's entries; chips: short totals like 'Water 64 / 64 oz'."""
        self.title.configure(text=_day_title(day))
        for w in self.chips.winfo_children():
            w.destroy()
        for i, (text, done) in enumerate(chips):   # five to a row so they never run off
            tk.Label(self.chips, text=text, bg=theme.SELECT if done else theme.RAISED,
                     fg=theme.BRIGHT, font=(FONT, 9), padx=10, pady=3).grid(
                row=i // 5, column=i % 5, sticky="w", padx=(0, 6), pady=(0, 4))

        view = day_view(rows)
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not view["groups"]:
            t.insert("end", "Nothing logged this day.", "empty")
        for group in view["groups"]:
            t.insert("end", group["time"] + "\t", ("time", "entry"))
            line_has_text = bool(group["notes"])
            if line_has_text:
                t.insert("end", join_notes(group["notes"]), "entry")
            if group["tags"]:
                if line_has_text:
                    t.insert("end", "\n\t", "entry")
                for kind, text in group["tags"]:
                    t.insert("end", f" {text} ", (kind, "entry"))
                    t.insert("end", "  ", "entry")
            t.insert("end", "\n", "entry")
        t.configure(state="disabled")


class ChartsTab(ttk.Frame):
    """Totals, symptoms and water through the day, and the last 14 days at a glance."""

    def __init__(self, master):
        super().__init__(master, padding=(0, 6, 0, 0))
        self._data = None
        self.title = ttk.Label(self, style="Title.TLabel", font=(FONT, 18, "bold"))
        self.title.pack(anchor="w")
        self.tiles = ttk.Frame(self)
        self.tiles.pack(fill="x", pady=(8, 10))

        self.chart = tk.Canvas(self, bg=theme.SURFACE, highlightthickness=0, height=230)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda _: self._draw_chart())

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=True, pady=(10, 0))
        self.heat = tk.Canvas(bottom, bg=theme.SURFACE, highlightthickness=0, width=300, height=150)
        self.heat.pack(side="left", fill="y")
        notes = ttk.Frame(bottom, style="Card.TFrame", padding=(12, 8))
        notes.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(notes, text="NOTES", style="CardMuted.TLabel").pack(anchor="w")
        self.notes = tk.Text(notes, wrap="word", bg=theme.SURFACE, fg=theme.BRIGHT, bd=0,
                             highlightthickness=0, font=(FONT, 10), height=6, cursor="arrow",
                             takefocus=0)
        self.notes.pack(fill="both", expand=True)
        self.notes.tag_configure("time", foreground=theme.MUTED)
        self.notes.tag_configure("entry", lmargin2=72, tabs=(72,), spacing1=4)

    def show(self, day, rows, tiles, heat):
        """tiles: [(label, value, fraction 0-1 or None, color, sub)];
        heat: [(date, peak or None)] oldest first."""
        self.title.configure(text=_day_title(day))
        for w in self.tiles.winfo_children():
            w.destroy()
        for i, (label, value, frac, color, sub) in enumerate(tiles):
            card = ttk.Frame(self.tiles, style="Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            self.tiles.columnconfigure(i, weight=1, uniform="tile")
            ttk.Label(card, text=label, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Label(card, text=value, style="CardBig.TLabel", font=(FONT, 16, "bold")).pack(anchor="w")
            bar = tk.Canvas(card, height=6, bg=theme.RAISED, highlightthickness=0)
            bar.pack(fill="x", pady=(2, 2))
            if frac is not None:
                bar.bind("<Configure>", lambda e, b=bar, f=frac, c=color: (
                    b.delete("all"), b.create_rectangle(0, 0, e.width * min(f, 1), 6, fill=c, width=0)))
            ttk.Label(card, text=sub, style="CardMuted.TLabel").pack(anchor="w")

        view = day_view(rows)
        self._data = view
        self._draw_chart()
        self._draw_heat(heat)

        n = self.notes
        n.configure(state="normal")
        n.delete("1.0", "end")
        for group in view["groups"]:
            if group["notes"]:
                n.insert("end", group["time"] + "\t", ("time", "entry"))
                n.insert("end", join_notes(group["notes"]) + "\n", "entry")
        if not any(g["notes"] for g in view["groups"]):
            n.insert("end", "No notes this day.", "time")
        n.configure(state="disabled")

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        view = self._data
        if not view:
            return
        w, h = max(c.winfo_width(), 300), int(c["height"])
        left, right, top, bottom = 44, w - 50, 34, h - 26
        hours = [x for pts in view["series"].values() for x, _ in pts] + [x for x, _ in view["water"]]
        start = min([8] + [int(x) for x in hours])
        end = max([18] + [int(x) + 1 for x in hours])
        top_sev = max([6] + [s for pts in view["series"].values() for _, s in pts])
        top_oz = max([64] + [oz for _, oz in view["water"]])
        x_of = lambda hr: left + (hr - start) / (end - start) * (right - left)
        y_sev = lambda s: bottom - s / top_sev * (bottom - top)
        y_oz = lambda oz: bottom - oz / top_oz * (bottom - top)

        c.create_text(12, 14, text="Symptoms (out of 10) and water through the day", anchor="w",
                      fill=theme.BRIGHT, font=(FONT, 10, "bold"))
        for frac in (0, 0.5, 1):
            y = bottom - frac * (bottom - top)
            c.create_line(left, y, right, y, fill=theme.RAISED)
            c.create_text(left - 8, y, text=f"{top_sev * frac:g}", anchor="e", fill=theme.MUTED, font=(FONT, 8))
            c.create_text(right + 8, y, text=f"{top_oz * frac:.0f} oz", anchor="w", fill=theme.MUTED, font=(FONT, 8))
        for hr in range(start, end + 1, 2):
            label = dt.time(hr % 24).strftime("%I%p").lstrip("0").lower()
            c.create_text(x_of(hr), bottom + 12, text=label, fill=theme.MUTED, font=(FONT, 8))

        if view["water"]:  # running total as a dashed step line
            pts = [(x_of(start), y_oz(0))]
            for hr, oz in view["water"]:
                pts += [(x_of(hr), pts[-1][1]), (x_of(hr), y_oz(oz))]
            pts.append((x_of(end), pts[-1][1]))
            c.create_line(*[v for p in pts for v in p], fill=theme.TEXT, dash=(4, 3), width=1.5)

        legend_x = right
        for name, pts in sorted(view["series"].items()):
            color = theme.SERIES_COLORS.get(name, theme.SERIES_COLORS["Other"])
            line = [(x_of(hr), y_sev(s)) for hr, s in pts] + [(x_of(end), y_sev(pts[-1][1]))]
            if len(line) > 1:
                c.create_line(*[v for p in line for v in p], fill=color, width=2.5)
            for hr, s in pts:
                x, y = x_of(hr), y_sev(s)
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="")
            item = c.create_text(legend_x, 14, text=name, anchor="e", fill=theme.TEXT, font=(FONT, 9))
            x0 = c.bbox(item)[0]
            c.create_rectangle(x0 - 14, 9, x0 - 4, 19, fill=color, outline="")
            legend_x = x0 - 24

    def _draw_heat(self, heat):
        c = self.heat
        c.delete("all")
        c.create_text(12, 14, text="Worst rating, last 14 days", anchor="w",
                      fill=theme.BRIGHT, font=(FONT, 10, "bold"))
        size, gap = 34, 6
        for i, (day, peak) in enumerate(heat):
            row, col = divmod(i, 7)
            x, y = 12 + col * (size + gap), 32 + row * (size + gap + 12)
            level = 0 if peak is None else min(4, max(1, int(-(-peak // 1))))
            color = theme.HEAT[level]
            c.create_rectangle(x, y, x + size, y + size, fill=color, outline="")
            fg = theme.MUTED if level == 0 else (theme.BRIGHT if level == 1 else theme.BG)
            c.create_text(x + size / 2, y + size / 2, text="–" if peak is None else f"{peak:g}",
                          fill=fg, font=(FONT, 9, "bold"))
            c.create_text(x + size / 2, y + size + 7, text=day.strftime("%a")[:2],
                          fill=theme.MUTED, font=(FONT, 7))
