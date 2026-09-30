"""The desktop window."""

import datetime as dt
import logging
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_DIR, config, creds, mailer, report, startup, theme
from . import weather as wx
from .parser import CATEGORIES, LABELS, split_time
from .service import DAYS, Worker, next_reminder
from .store import Store

LABEL_TO_CAT = {v: k for k, v in LABELS.items()}
MODES = {"normal": "Normal", "rough": "Rough day (1 check-in)", "pause": "Paused today"}
REPORTS_DIR = APP_DIR / "reports"


def _fmt(ts):
    return ts.strftime("%I:%M %p").lstrip("0")


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, on_save):
        super().__init__(master)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(master)
        theme.dialog(self)
        self.on_save = on_save
        cfg = self.cfg = config.load()
        has_pw = bool(cfg["tracker_email"] and creds.get_password(cfg["tracker_email"]))
        self.vars = {}

        outer = ttk.Frame(self, padding=12)
        outer.grid(sticky="nsew")
        nb = ttk.Notebook(outer)
        nb.grid(row=0, column=0, sticky="nsew")
        tabs = {}
        for name in ("Email", "Reminders", "Tracking"):
            tabs[name] = ttk.Frame(nb, padding=14)
            nb.add(tabs[name], text=name)

        def row(tab, r, label, key, value, hint="", show=None, width=44):
            frm = tabs[tab]
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="nw", pady=4, padx=(0, 10))
            var = tk.StringVar(value=value)
            ttk.Entry(frm, textvariable=var, width=width, show=show).grid(row=r, column=1, sticky="w")
            if hint:
                ttk.Label(frm, text=hint, style="Muted.TLabel").grid(row=r + 1, column=1, sticky="w")
            self.vars[key] = var

        # Email
        row("Email", 0, "Tracker Gmail address", "tracker_email", cfg["tracker_email"])
        row("Email", 1, "Gmail app password", "password", "", show="•",
            hint="Saved in Windows Credential Manager." + (" Leave blank to keep the saved one." if has_pw else ""))
        row("Email", 3, "Accept logs from", "allowed_senders", ", ".join(cfg["allowed_senders"]),
            hint="Your own addresses, comma separated. Other senders are ignored.")
        row("Email", 5, "Send reminders to", "reminder_to", cfg["reminder_to"])
        row("Email", 6, "Check inbox every (minutes)", "poll_minutes", str(cfg["poll_minutes"]), width=8)
        ttk.Label(tabs["Email"], text="Reply to my log emails").grid(row=7, column=0, sticky="w", pady=4)
        self.reply_mode = tk.StringVar(value=cfg["reply_to_logs"])
        ttk.Combobox(tabs["Email"], textvariable=self.reply_mode, state="readonly", width=12,
                     values=["errors", "always", "never"]).grid(row=7, column=1, sticky="w")
        ttk.Label(tabs["Email"], text="errors = only when an email couldn't be read",
                  style="Muted.TLabel").grid(row=8, column=1, sticky="w")
        ttk.Button(tabs["Email"], text="Test connection", command=self.test).grid(
            row=9, column=1, sticky="w", pady=(10, 0))

        # Reminders
        row("Reminders", 0, "Reminder times", "reminder_times", ", ".join(cfg["reminder_times"]),
            hint="24-hour times, comma separated, e.g. 09:00, 12:00, 14:00")
        row("Reminders", 2, "Reminder days", "reminder_days", ", ".join(cfg["reminder_days"]),
            hint="Mon, Tue, Wed, Thu, Fri, Sat, Sun")
        row("Reminders", 4, "Skip if I logged in the last", "skip_if_logged_minutes",
            str(cfg["skip_if_logged_minutes"]), hint="minutes (0 = never skip)", width=8)
        self.summary_on = tk.BooleanVar(value=cfg["summary_enabled"])
        ttk.Checkbutton(tabs["Reminders"], text="Email me a weekly summary",
                        variable=self.summary_on).grid(row=6, column=1, sticky="w", pady=(10, 2))
        ttk.Label(tabs["Reminders"], text="Weekly summary on").grid(row=7, column=0, sticky="w", pady=4)
        when = ttk.Frame(tabs["Reminders"])
        when.grid(row=7, column=1, sticky="w")
        self.summary_day = tk.StringVar(value=cfg["summary_day"])
        ttk.Combobox(when, textvariable=self.summary_day, state="readonly", width=6,
                     values=DAYS).pack(side="left")
        ttk.Label(when, text=" at ").pack(side="left")
        self.vars["summary_time"] = tk.StringVar(value=cfg["summary_time"])
        ttk.Entry(when, textvariable=self.vars["summary_time"], width=7).pack(side="left")

        # Tracking
        row("Tracking", 0, "Daily water goal (oz)", "water_goal_oz", str(cfg["water_goal_oz"]), width=8)
        row("Tracking", 1, "Weather location", "weather_place", cfg["weather_place"],
            hint=(f"Using {cfg['weather_label']}. " if cfg["weather_label"] else "")
            + "ZIP code or \"City, ST\". Leave blank to turn weather off.")
        row("Tracking", 3, "Pollen report emails from", "pollen_senders", ", ".join(cfg["pollen_senders"]),
            hint="The sender address (or just its domain) of your pollen alert emails.")
        row("Tracking", 5, "Caffeine per drink (mg)", "caffeine_drinks",
            config.drinks_to_text(cfg["caffeine_drinks"]),
            hint="\"3/4 monster\" is logged with its mg. Add more like: red bull = 80")
        ttk.Label(tabs["Tracking"], text="Short codes").grid(row=7, column=0, sticky="nw", pady=4)
        self.codes = tk.Text(tabs["Tracking"], width=44, height=9, **theme.text_widget_options())
        self.codes.insert("1.0", config.codes_to_text(cfg["short_codes"]))
        self.codes.grid(row=7, column=1, sticky="w", pady=4)
        ttk.Label(tabs["Tracking"], style="Muted.TLabel",
                  text="code = category: text   {n} = the number, {text} = the words after it").grid(
            row=8, column=1, sticky="w")

        bottom = ttk.Frame(outer)
        bottom.grid(row=1, column=0, sticky="we", pady=(12, 0))
        self.autostart = tk.BooleanVar(value=startup.is_enabled())
        ttk.Checkbutton(bottom, text="Start with Windows (opens minimized)",
                        variable=self.autostart).pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", style="Accent.TButton", command=self.save).pack(side="right", padx=6)
        self.grab_set()

    def _collect(self):
        cfg = config.load()
        v = {k: var.get().strip() for k, var in self.vars.items()}
        split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
        times = [dt.datetime.strptime(t, "%H:%M").strftime("%H:%M") for t in split(v["reminder_times"])]
        days = [d.title()[:3] for d in split(v["reminder_days"])]
        bad = [d for d in days if d not in DAYS]
        if bad:
            raise ValueError(f"Unknown day: {', '.join(bad)}")
        cfg.update(
            tracker_email=v["tracker_email"].lower(),
            allowed_senders=[a.lower() for a in split(v["allowed_senders"])],
            reminder_to=v["reminder_to"],
            reminder_times=times,
            reminder_days=days,
            poll_minutes=max(1, int(v["poll_minutes"])),
            reply_to_logs=self.reply_mode.get(),
            skip_if_logged_minutes=max(0, int(v["skip_if_logged_minutes"] or 0)),
            summary_enabled=self.summary_on.get(),
            summary_day=self.summary_day.get(),
            summary_time=dt.datetime.strptime(v["summary_time"], "%H:%M").strftime("%H:%M"),
            water_goal_oz=max(1, int(float(v["water_goal_oz"]))),
            weather_place=v["weather_place"],
            pollen_senders=[a.lower() for a in split(v["pollen_senders"])],
            short_codes=config.codes_from_text(self.codes.get("1.0", "end")),
            caffeine_drinks=config.drinks_from_text(v["caffeine_drinks"]),
        )
        return cfg, v["password"]

    def test(self):
        try:
            cfg, typed = self._collect()
            pw = "".join(typed.split()) or creds.get_password(cfg["tracker_email"])
            if not pw:
                raise ValueError("Enter the app password first.")
            self.config(cursor="watch")
            self.update()
            mailer.test_login(cfg, pw)
            messagebox.showinfo("Settings", "Connected to Gmail. Nothing was sent.", parent=self)
        except Exception as e:
            messagebox.showerror("Settings", f"Couldn't connect:\n{e}", parent=self)
        finally:
            self.config(cursor="")

    def save(self):
        try:
            cfg, typed = self._collect()
        except ValueError as e:
            messagebox.showerror("Settings", str(e), parent=self)
            return
        if not config.is_configured(cfg):
            messagebox.showerror("Settings", "Fill in the Gmail address, who to accept logs from, "
                                 "and where to send reminders.", parent=self)
            return
        if cfg["weather_place"] != self.cfg["weather_place"] or (
                cfg["weather_place"] and cfg["weather_lat"] is None):
            if cfg["weather_place"]:
                try:
                    self.config(cursor="watch")
                    self.update()
                    cfg["weather_lat"], cfg["weather_lon"], cfg["weather_label"] = wx.geocode(cfg["weather_place"])
                except Exception as e:
                    messagebox.showerror("Settings", f"Couldn't look up that weather location:\n{e}", parent=self)
                    return
                finally:
                    self.config(cursor="")
            else:
                cfg["weather_lat"] = cfg["weather_lon"] = None
                cfg["weather_label"] = ""
        if typed:
            creds.set_password(cfg["tracker_email"], typed)
        config.save(cfg)
        try:
            if self.autostart.get() != startup.is_enabled():
                startup.enable() if self.autostart.get() else startup.disable()
        except Exception as e:
            messagebox.showerror("Settings", f"Couldn't change the startup setting:\n{e}", parent=self)
        self.destroy()
        self.on_save()


class AddEntryDialog(tk.Toplevel):
    def __init__(self, master, on_add):
        super().__init__(master)
        self.title("Add entry")
        self.resizable(False, False)
        self.transient(master)
        theme.dialog(self)
        frm = ttk.Frame(self, padding=14)
        frm.grid()
        self.cat = tk.StringVar(value=LABELS["symptoms"])
        self.val = tk.StringVar()
        ttk.Combobox(frm, textvariable=self.cat, state="readonly", width=15,
                     values=[LABELS[c] for c in CATEGORIES]).grid(row=0, column=0, padx=(0, 6))
        e = ttk.Entry(frm, textvariable=self.val, width=40)
        e.grid(row=0, column=1)
        e.focus_set()
        e.bind("<Return>", lambda _: self.add())
        ttk.Button(frm, text="Add", style="Accent.TButton", command=self.add).grid(row=0, column=2, padx=(6, 0))
        ttk.Label(frm, text="End with @time to backdate, e.g. \"headache 5/10 @2pm\"",
                  style="Muted.TLabel").grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.on_add = on_add
        self.grab_set()

    def add(self):
        value, at = split_time(self.val.get().strip(), dt.datetime.now())
        if value:
            self.on_add(LABEL_TO_CAT[self.cat.get()], value, at)
        self.destroy()


class ReportDialog(tk.Toplevel):
    RANGES = {"Last 30 days": 30, "Last 90 days": 90, "Last 6 months": 182, "Last year": 365}

    def __init__(self, master, make):
        super().__init__(master)
        self.title("Doctor visit report")
        self.resizable(False, False)
        self.transient(master)
        theme.dialog(self)
        frm = ttk.Frame(self, padding=14)
        frm.grid()
        ttk.Label(frm, text="Cover").grid(row=0, column=0, padx=(0, 8))
        self.range = tk.StringVar(value="Last 90 days")
        ttk.Combobox(frm, textvariable=self.range, state="readonly", width=14,
                     values=list(self.RANGES)).grid(row=0, column=1)
        ttk.Button(frm, text="Create report", style="Accent.TButton",
                   command=lambda: (make(self.RANGES[self.range.get()]), self.destroy())).grid(
            row=0, column=2, padx=(8, 0))
        ttk.Label(frm, text="Opens in your browser. Use Print → Save as PDF to share it.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.grab_set()


class App(tk.Tk):
    def __init__(self, minimized=False):
        super().__init__()
        self.title("Symptom Tracker")
        self.geometry("920x580")
        self.minsize(760, 400)
        theme.apply(self)
        self.store = Store(config.DB_PATH)
        self.events = queue.Queue()
        self.worker = Worker(self.store, self.events)
        self.status = tk.StringVar(value="Starting…")
        self.summary = tk.StringVar()
        self.conditions = tk.StringVar()
        self.filter = tk.StringVar(value="All")
        self.mode = tk.StringVar()
        self._build()
        self.refresh()
        self.worker.start()
        self.after(500, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._close)
        if not config.is_configured(config.load()):
            self.status.set("Not set up yet. Open Settings to connect your tracker Gmail.")
            self.after(300, self.open_settings)
        elif minimized:
            self.iconify()

    def _build(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Button(top, text="Check inbox now",
                   command=lambda: self.worker.requests.put("check")).pack(side="left", padx=(0, 6))
        send = ttk.Menubutton(top, text="Send email")
        menu = tk.Menu(send, **theme.menu_options())
        menu.add_command(label="Check-in reminder now", command=self.remind_now)
        menu.add_command(label="Weekly summary now", command=self.summary_now)
        send["menu"] = menu
        send.pack(side="left", padx=(0, 6))
        for text, cmd in [("Add entry", lambda: AddEntryDialog(self, self.add_manual)),
                          ("Doctor report", lambda: ReportDialog(self, self.make_report)),
                          ("Export CSV", self.export),
                          ("Settings", self.open_settings)]:
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=(0, 6))

        info = ttk.Frame(self, padding=(12, 4, 12, 0))
        info.pack(fill="x")
        ttk.Label(info, textvariable=self.summary, style="Summary.TLabel").pack(side="left")
        cb = ttk.Combobox(info, textvariable=self.filter, state="readonly", width=15,
                          values=["All"] + [LABELS[c] for c in CATEGORIES])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Label(info, text="Show", style="Muted.TLabel").pack(side="right", padx=(12, 6))
        mode = ttk.Combobox(info, textvariable=self.mode, state="readonly", width=20,
                            values=list(MODES.values()))
        mode.pack(side="right")
        mode.bind("<<ComboboxSelected>>", self._mode_changed)
        ttk.Label(info, text="Today", style="Muted.TLabel").pack(side="right", padx=(0, 6))

        ttk.Label(self, textvariable=self.conditions, style="Muted.TLabel",
                  padding=(12, 2, 12, 4)).pack(fill="x")

        body = ttk.Frame(self, padding=(12, 4))
        body.pack(fill="both", expand=True)
        cols = ("when", "category", "value", "source")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in [("when", "When", 160, False), ("category", "Category", 110, False),
                                          ("value", "Entry", 420, True), ("source", "From", 70, False)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=stretch)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Delete>", self.delete_selected)

        ttk.Label(self, textvariable=self.status, padding=(12, 4, 12, 8),
                  style="Muted.TLabel").pack(fill="x")

    def refresh(self):
        cat = LABEL_TO_CAT.get(self.filter.get())
        self.tree.delete(*self.tree.get_children())
        for entry_id, when, category, value, source in self.store.recent(category=cat):
            stamp = dt.datetime.fromisoformat(when).strftime("%a %b %d  %I:%M %p")
            self.tree.insert("", "end", iid=str(entry_id),
                             values=(stamp, LABELS.get(category, category), value, source))
        cfg = self.worker.cfg
        today = dt.date.today()
        t = self.store.day_totals(today)
        rescue = self.store.rescue_days(today.year, today.month)
        parts = [f"Water {t['water']:.0f}/{cfg['water_goal_oz']} oz"]
        if t["electrolytes"]:
            parts.append(f"Electrolytes {t['electrolytes']:g}")
        if t["caffeine_mg"]:
            parts.append(f"Caffeine {t['caffeine_mg']:.0f} mg")
        elif t["caffeine"]:
            parts.append(f"Caffeine {t['caffeine']:g}")
        parts.append(f"Rescue med days this month {rescue}/10" + (" ⚠" if rescue >= 8 else ""))
        self.summary.set("   ·   ".join(parts))

        w = self.store.weather(today - dt.timedelta(days=1), today)
        line = wx.describe(w.get(str(today)), wx.pressure_change(
            w.get(str(today)), w.get(str(today - dt.timedelta(days=1)))))
        pollen = self.store.pollen(today, today).get(str(today))
        bits = ([f"Weather: {line}"] if line else []) + ([f"Pollen: {pollen}"] if pollen else [])
        self.conditions.set("   ·   ".join(bits))
        self.mode.set(MODES[self.store.day_mode()])

    def _status_line(self, lead):
        cfg = self.worker.cfg
        nxt = (next_reminder(cfg, dt.datetime.now(), self.store.day_mode)
               if config.is_configured(cfg) else None)
        tail = f"  ·  Next reminder {nxt.strftime('%a')} {_fmt(nxt)}" if nxt else ""
        self.status.set(lead + tail)

    def _pump(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            now = _fmt(dt.datetime.now())
            if kind == "checked":
                new = f", {data} new item(s)" if data else ""
                self._status_line(f"Checked inbox at {now}{new}")
                self.refresh()
            elif kind == "reminded":
                self._status_line(f"Sent reminder at {now}")
            elif kind == "skipped":
                self._status_line(f"Skipped the {_fmt(data)} reminder since you logged recently")
            elif kind == "summary":
                self._status_line(f"Sent weekly summary at {now}")
            elif kind in ("weather", "mode"):
                self.refresh()
            elif kind == "error":
                self.status.set(f"Problem: {data}  (details in tracker.log)")
        self.after(1000, self._pump)

    def _mode_changed(self, _=None):
        mode = next(k for k, v in MODES.items() if v == self.mode.get())
        self.store.set_day_mode(mode)
        self._status_line(f"Today set to: {self.mode.get()}")

    def remind_now(self):
        if messagebox.askyesno("Send reminder", "Send a check-in email now?", parent=self):
            self.worker.requests.put("remind")

    def summary_now(self):
        if messagebox.askyesno("Weekly summary", "Email the summary of the last 7 days now?", parent=self):
            self.worker.requests.put("summary")

    def make_report(self, days):
        end = dt.date.today()
        start = end - dt.timedelta(days=days - 1)
        html = report.doctor_report(self.worker.cfg, self.store, start, end)
        REPORTS_DIR.mkdir(exist_ok=True)
        path = REPORTS_DIR / f"doctor-report-{end}.html"
        path.write_text(html, encoding="utf-8")
        os.startfile(path)
        self.status.set(f"Report saved to {path}")

    def add_manual(self, category, value, at=None):
        self.store.add_entries([(category, value, at)], source="manual")
        self.refresh()

    def delete_selected(self, _=None):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Delete", "Delete the selected entry?", parent=self):
            self.store.delete(int(sel[0]))
            self.refresh()

    def export(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"symptom-log-{dt.date.today().isoformat()}.csv")
        if path:
            n = self.store.export_csv(path)
            self.status.set(f"Exported {n} entries to {path}")

    def open_settings(self):
        SettingsDialog(self, on_save=self._settings_saved)

    def _settings_saved(self):
        self.worker.requests.put("reload")
        self.status.set("Settings saved. Checking inbox…")
        self.after(1500, self.refresh)

    def _close(self):
        self.worker.stop()
        self.destroy()


def main():
    logging.basicConfig(filename=config.LOG_PATH, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App(minimized="--minimized" in sys.argv).mainloop()
