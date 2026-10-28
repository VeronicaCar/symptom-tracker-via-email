"""What the HTML window asks for. Each public method of Api is callable from the
page's JavaScript (POST /api/<name>, see webui.py) and returns plain JSON data, so
this file can be tested without a window."""

import datetime as dt
import logging
import os
import queue
import subprocess
import sys
from pathlib import Path

from . import APP_DIR, config, creds, mailer, report, startup
from . import weather as wx
from .dayview import day_blurb, day_view, join_notes, peak_of_day, series_for
from .parser import CATEGORIES, LABELS, split_time
from .service import DAYS, next_reminder

log = logging.getLogger(__name__)

REPORTS_DIR = APP_DIR / "reports"
MODES = {"normal": "Normal", "rough": "Rough day (1 check-in)", "pause": "Paused today"}
REPORT_RANGES = {"Last 30 days": 30, "Last 90 days": 90, "Last 6 months": 182, "Last year": 365}


def _fmt(ts):
    return ts.strftime("%I:%M %p").lstrip("0")


def _day_title(day):
    return day.strftime("%A, %B ") + str(day.day)


def settings_form(cfg):
    """The settings page's fields, as text."""
    return {
        "tracker_email": cfg["tracker_email"],
        "password": "",
        "allowed_senders": ", ".join(cfg["allowed_senders"]),
        "reminder_to": cfg["reminder_to"],
        "poll_minutes": str(cfg["poll_minutes"]),
        "reply_to_logs": cfg["reply_to_logs"],
        "reminder_times": ", ".join(cfg["reminder_times"]),
        "reminder_days": ", ".join(cfg["reminder_days"]),
        "skip_if_logged_minutes": str(cfg["skip_if_logged_minutes"]),
        "summary_enabled": cfg["summary_enabled"],
        "summary_day": cfg["summary_day"],
        "summary_time": cfg["summary_time"],
        "send_reminders": cfg["send_reminders"],
        "water_goal_oz": str(cfg["water_goal_oz"]),
        "weather_place": cfg["weather_place"],
        "weather_label": cfg["weather_label"],
        "pollen_senders": ", ".join(cfg["pollen_senders"]),
        "caffeine_drinks": config.drinks_to_text(cfg["caffeine_drinks"]),
        "short_codes": config.codes_to_text(cfg["short_codes"]),
    }


def config_from_form(form, cfg):
    """Apply the settings page's fields to cfg. Raises ValueError with a readable message."""
    v = {k: (val.strip() if isinstance(val, str) else val) for k, val in form.items()}
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    try:
        times = [dt.datetime.strptime(t, "%H:%M").strftime("%H:%M") for t in split(v["reminder_times"])]
        summary_time = dt.datetime.strptime(v["summary_time"], "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ValueError("Times need to look like 09:00 or 14:30.") from None
    days = [d.title()[:3] for d in split(v["reminder_days"])]
    bad = [d for d in days if d not in DAYS]
    if bad:
        raise ValueError(f"Unknown day: {', '.join(bad)}")
    try:
        numbers = dict(poll=max(1, int(v["poll_minutes"])),
                       skip=max(0, int(v["skip_if_logged_minutes"] or 0)),
                       water=max(1, int(float(v["water_goal_oz"]))))
    except ValueError:
        raise ValueError("Minutes and the water goal need to be numbers.") from None
    cfg = dict(cfg)
    cfg.update(
        tracker_email=v["tracker_email"].lower(),
        allowed_senders=[a.lower() for a in split(v["allowed_senders"])],
        reminder_to=v["reminder_to"],
        reminder_times=times,
        reminder_days=days,
        poll_minutes=numbers["poll"],
        reply_to_logs=v["reply_to_logs"] if v["reply_to_logs"] in ("errors", "always", "never") else "errors",
        skip_if_logged_minutes=numbers["skip"],
        summary_enabled=bool(v["summary_enabled"]),
        send_reminders=bool(v["send_reminders"]),
        summary_day=v["summary_day"] if v["summary_day"] in DAYS else "Sun",
        summary_time=summary_time,
        water_goal_oz=numbers["water"],
        weather_place=v["weather_place"],
        pollen_senders=[a.lower() for a in split(v["pollen_senders"])],
        short_codes=config.codes_from_text(v["short_codes"]),
        caffeine_drinks=config.drinks_from_text(v["caffeine_drinks"]),
    )
    return cfg


class Api:
    def __init__(self, store, worker):
        self._store = store
        self._worker = worker
        self._status = "Starting…"

    # ---- reading ------------------------------------------------------------

    def view(self, day=None):
        """Everything the page shows, for one day (ISO date; default today)."""
        store, cfg = self._store, self._worker.cfg
        today = dt.date.today()
        day = dt.date.fromisoformat(day) if day else today
        by_day = {}
        for row in store.between(today - dt.timedelta(days=59), today + dt.timedelta(days=1)):
            by_day.setdefault(dt.date.fromisoformat(row[0][:10]), []).append(row)
        rows = by_day.get(day) or store.between(day, day + dt.timedelta(days=1))
        if day not in by_day:
            by_day[day] = rows

        goal = cfg["water_goal_oz"]
        t = store.day_totals(day)
        rescue = store.rescue_days(day.year, day.month)
        advil = store.days_with("advil", day.year, day.month)
        dv = day_view(rows)
        chips = [{"text": f"Water {t['water']:.0f} / {goal} oz" + (" ✓" if t["water"] >= goal else ""),
                  "done": t["water"] >= goal}]
        if t["caffeine_mg"]:
            chips.append({"text": f"Caffeine {t['caffeine_mg']:.0f} mg", "done": False})
        elif t["caffeine"]:
            chips.append({"text": f"Caffeine {t['caffeine']:g}", "done": False})
        if t["electrolytes"]:
            chips.append({"text": f"Electrolytes {t['electrolytes']:g}", "done": False})
        chips += [{"text": f"{name} peak {sev:g}/10", "done": False} for name, sev in sorted(dv["peaks"].items())]

        w = store.weather(day - dt.timedelta(days=1), day)
        conditions = wx.describe(w.get(str(day)), wx.pressure_change(
            w.get(str(day)), w.get(str(day - dt.timedelta(days=1)))))
        pollen = store.pollen(day, day).get(str(day))

        groups = [{"time": g["time"], "note": join_notes(g["notes"]),
                   "tags": [{"kind": k, "text": x} for k, x in g["tags"]]} for g in dv["groups"]]
        caffeine = f"{t['caffeine_mg']:.0f} mg" if t["caffeine_mg"] else f"{t['caffeine']:g}"
        return {
            "day": str(day),
            "today": str(today),
            "title": _day_title(day),
            "conditions": " · ".join(x for x in (conditions, f"Pollen: {pollen}" if pollen else "") if x),
            "chips": chips,
            "groups": groups,
            "series": {name: pts for name, pts in dv["series"].items()},
            "water": dv["water"],
            "water_goal": goal,
            "tiles": [
                {"label": "Water", "value": f"{t['water']:.0f} oz", "frac": t["water"] / goal if goal else 0,
                 "kind": "water", "sub": f"Goal {goal} oz"},
                {"label": "Caffeine", "value": caffeine, "frac": t["caffeine_mg"] / 400 if t["caffeine_mg"] else 0,
                 "kind": "caffeine", "sub": "Limit 400 mg"},
                {"label": "Electrolytes", "value": f"{t['electrolytes']:g}", "frac": t["electrolytes"] / 2,
                 "kind": "accent", "sub": "Servings"},
                {"label": "Rescue-med days", "value": f"{rescue} / 10", "frac": rescue / 10,
                 "kind": "med", "sub": "This month" + (" · near the limit" if rescue >= 8 else ""),
                 "warn": rescue >= 8},
                {"label": "Advil days", "value": f"{advil} / 15", "frac": advil / 15,
                 "kind": "med", "sub": "This month" + (" · near the limit" if advil >= 12 else ""),
                 "warn": advil >= 12},
            ],
            "days": [{"day": str(d), "label": d.strftime("%a %b ") + str(d.day), "count": len(r),
                      "blurb": day_blurb(r)} for d, r in sorted(by_day.items(), reverse=True)],
            "heat": [{"day": str(d), "label": d.strftime("%a")[:2], "peak": peak_of_day(by_day.get(d, []))}
                     for d in (today - dt.timedelta(days=13 - i) for i in range(14))],
            "mode": store.day_mode(),
            "modes": MODES,
            "categories": [{"key": c, "label": LABELS[c]} for c in CATEGORIES],
            "status": self._status_line(),
            "configured": config.is_configured(cfg),
        }

    def entries(self, category=None):
        """The All entries table: the 300 most recent, optionally one category."""
        rows = self._store.recent(category=category or None)
        return [{"id": i, "when": dt.datetime.fromisoformat(w).strftime("%a %b %d  %I:%M %p"),
                 "category": LABELS.get(c, c), "value": v, "source": s} for i, w, c, v, s in rows]

    def poll(self):
        """Worker news since the last call: {"status": text, "refresh": bool}."""
        refresh = False
        while True:
            try:
                kind, data = self._worker.events.get_nowait()
            except queue.Empty:
                break
            now = _fmt(dt.datetime.now())
            if kind == "checked":
                self._status = f"Checked inbox at {now}" + (f", {data} new item(s)" if data else "")
                refresh = True
            elif kind == "reminded":
                self._status = f"Sent reminder at {now}"
            elif kind == "skipped":
                self._status = f"Skipped the {_fmt(data)} reminder since you logged recently"
            elif kind == "summary":
                self._status = f"Sent weekly summary at {now}"
            elif kind in ("weather", "mode"):
                refresh = True
            elif kind == "error":
                self._status = f"Problem: {data}  (details in tracker.log)"
        return {"status": self._status_line(), "refresh": refresh}

    def _status_line(self):
        cfg = self._worker.cfg
        if not config.is_configured(cfg):
            return "Not set up yet. Open Settings to connect your tracker Gmail."
        today = dt.date.today()
        mode = self._store.day_mode()
        nxt = (next_reminder(cfg, dt.datetime.now(), lambda d: mode if d == today else "normal")
               if cfg["send_reminders"] else None)
        return self._status + (f"  ·  Next reminder {nxt.strftime('%a')} {_fmt(nxt)}" if nxt else "")

    # ---- changes ------------------------------------------------------------

    def add_entry(self, category, text):
        value, at = split_time((text or "").strip(), dt.datetime.now())
        if not value or category not in CATEGORIES:
            return {"ok": False, "error": "Type something to log."}
        self._store.add_entries([(category, value, at)], source="manual")
        return {"ok": True}

    def delete_entry(self, entry_id):
        self._store.delete(int(entry_id))
        return {"ok": True}

    def set_mode(self, mode):
        if mode in MODES:
            self._store.set_day_mode(mode)
            self._status = f"Today set to: {MODES[mode]}"
        return {"ok": True}

    def request(self, job):
        """'check', 'remind' or 'summary': handed to the background worker."""
        if job in ("check", "remind", "summary"):
            self._worker.requests.put(job)
            self._status = {"check": "Checking inbox…", "remind": "Sending a reminder…",
                            "summary": "Sending the weekly summary…"}[job]
        return {"ok": True}

    def report_ranges(self):
        return list(REPORT_RANGES)

    def make_report(self, label):
        days = REPORT_RANGES.get(label, 30)
        end = dt.date.today()
        html = report.doctor_report(self._worker.cfg, self._store, end - dt.timedelta(days=days - 1), end)
        REPORTS_DIR.mkdir(exist_ok=True)
        path = REPORTS_DIR / f"doctor-report-{end}.html"
        path.write_text(html, encoding="utf-8")
        if hasattr(os, "startfile"):
            os.startfile(path)
        self._status = f"Report saved to {path}"
        return {"ok": True, "path": str(path)}

    def export_csv(self):
        """Save everything to a CSV in Downloads and show it in File Explorer."""
        folder = Path.home() / "Downloads"
        folder.mkdir(exist_ok=True)
        path = folder / f"symptom-log-{dt.date.today().isoformat()}.csv"
        n = self._store.export_csv(path)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        self._status = f"Exported {n} entries to {path}"
        return {"ok": True, "path": str(path)}

    # ---- settings -----------------------------------------------------------

    def get_settings(self):
        cfg = config.load()
        form = settings_form(cfg)
        form["has_password"] = bool(cfg["tracker_email"] and creds.get_password(cfg["tracker_email"]))
        form["autostart"] = startup.is_enabled()
        form["days"] = DAYS
        return form

    def test_connection(self, form):
        try:
            cfg = config_from_form(form, config.load())
            pw = "".join((form.get("password") or "").split()) or creds.get_password(cfg["tracker_email"])
            if not pw:
                raise ValueError("Enter the app password first.")
            mailer.test_login(cfg, pw)
        except Exception as e:
            return {"ok": False, "error": f"Couldn't connect: {e}"}
        return {"ok": True, "message": "Connected to Gmail. Nothing was sent."}

    def save_settings(self, form):
        old = config.load()
        try:
            cfg = config_from_form(form, old)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not config.is_configured(cfg):
            return {"ok": False, "error": "Fill in the Gmail address, who to accept logs from, "
                                          "and where to send reminders."}
        if cfg["weather_place"] != old["weather_place"] or (cfg["weather_place"] and cfg["weather_lat"] is None):
            if cfg["weather_place"]:
                try:
                    cfg["weather_lat"], cfg["weather_lon"], cfg["weather_label"] = wx.geocode(cfg["weather_place"])
                except Exception as e:
                    return {"ok": False, "error": f"Couldn't look up that weather location: {e}"}
            else:
                cfg["weather_lat"] = cfg["weather_lon"] = None
                cfg["weather_label"] = ""
        typed = (form.get("password") or "").strip()
        if typed:
            creds.set_password(cfg["tracker_email"], typed)
        config.save(cfg)
        try:
            if bool(form.get("autostart")) != startup.is_enabled():
                startup.enable() if form.get("autostart") else startup.disable()
        except Exception as e:
            return {"ok": False, "error": f"Settings saved, but the startup setting couldn't change: {e}"}
        self._worker.requests.put("reload")
        self._status = "Settings saved. Checking inbox…"
        return {"ok": True}
