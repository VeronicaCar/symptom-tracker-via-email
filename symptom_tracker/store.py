"""Local SQLite storage for log entries, daily weather and pollen."""

import csv
import datetime as dt
import re
import sqlite3
from contextlib import closing

from .parser import SEVERITY_CATEGORIES, normalize, severity_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY,
    logged_at   TEXT NOT NULL,      -- local time the thing happened
    category    TEXT NOT NULL,
    value       TEXT NOT NULL,
    severity    INTEGER,            -- 0-10 when the text has "n/10"
    source      TEXT NOT NULL,      -- 'email' or 'manual'
    message_id  TEXT
);
CREATE TABLE IF NOT EXISTS processed (
    message_id   TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    slot    TEXT PRIMARY KEY,       -- 'YYYY-MM-DD HH:MM', or 'summary YYYY-MM-DD'
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weather (
    day            TEXT PRIMARY KEY,  -- 'YYYY-MM-DD'
    temp_max       REAL,              -- °F
    temp_min       REAL,
    humidity       REAL,              -- mean %
    pressure_mean  REAL,              -- hPa, sea level
    pressure_min   REAL,
    pressure_max   REAL,
    precip         REAL,              -- inches
    fetched_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pollen (
    day          TEXT PRIMARY KEY,
    summary      TEXT NOT NULL,
    raw          TEXT,
    received_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS day_modes (
    day   TEXT PRIMARY KEY,
    mode  TEXT NOT NULL             -- 'rough' or 'pause'
);
"""

_OZ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(oz|ounces?|cups?|ml|l|liters?|litres?)\b", re.I)
_OZ_PER = {"oz": 1, "ounce": 1, "ounces": 1, "cup": 8, "cups": 8, "ml": 1 / 29.57,
           "l": 33.81, "liter": 33.81, "liters": 33.81, "litre": 33.81, "litres": 33.81}
_COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)")


def water_ounces(value):
    return sum(float(n) * _OZ_PER[u.lower()] for n, u in _OZ_RE.findall(value))


def servings(value):
    """'2 cups' -> 2, 'coffee' -> 1. Used for caffeine and electrolytes."""
    m = _COUNT_RE.match(value) or re.search(r"\b(\d+(?:\.\d+)?)\b", value)
    return float(m.group(1)) if m else 1.0


def _now():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _iso(when):
    return when.replace(microsecond=0).isoformat(sep=" ")


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(entries)")}
            if "created_at" not in cols:
                c.execute("ALTER TABLE entries ADD COLUMN created_at TEXT")
                c.execute("UPDATE entries SET created_at = logged_at")
                c.commit()

    def _conn(self):
        # A fresh connection per call keeps this safe to use from the GUI and
        # the background checker at the same time.
        return closing(sqlite3.connect(self.path, timeout=10))

    # ---- entries ----------------------------------------------------------

    def add_entries(self, entries, when=None, source="email", message_id=None):
        """entries: (category, value) or (category, value, at) tuples."""
        when = when or dt.datetime.now()
        rows = []
        for e in entries:
            cat, val = e[0], normalize(e[0], e[1])
            at = e[2] if len(e) > 2 and e[2] else when
            sev = severity_of(val) if cat in SEVERITY_CATEGORIES else None
            rows.append((_iso(at), cat, val, sev, source, message_id, _now()))
        with self._conn() as c, c:
            c.executemany(
                "INSERT INTO entries (logged_at, category, value, severity, source,"
                " message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            if message_id:
                c.execute("INSERT OR IGNORE INTO processed VALUES (?, ?)", (message_id, _now()))

    def mark_processed(self, message_id):
        with self._conn() as c, c:
            c.execute("INSERT OR IGNORE INTO processed VALUES (?, ?)", (message_id, _now()))

    def is_processed(self, message_id):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM processed WHERE message_id = ?",
                             (message_id,)).fetchone() is not None

    def recent(self, limit=300, category=None):
        sql = "SELECT id, logged_at, category, value, source FROM entries"
        args = []
        if category:
            sql += " WHERE category = ?"
            args.append(category)
        sql += " ORDER BY logged_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return c.execute(sql, args).fetchall()

    def between(self, start, end):
        """Entries with start <= logged_at < end (dates or datetimes), oldest first."""
        with self._conn() as c:
            return c.execute(
                "SELECT logged_at, category, value, severity FROM entries"
                " WHERE logged_at >= ? AND logged_at < ? ORDER BY logged_at, id",
                (str(start), str(end))).fetchall()

    def last_created(self):
        with self._conn() as c:
            row = c.execute("SELECT MAX(created_at) FROM entries").fetchone()
        return dt.datetime.fromisoformat(row[0]) if row and row[0] else None

    def delete(self, entry_id):
        with self._conn() as c, c:
            c.execute("DELETE FROM entries WHERE id = ?", (entry_id,))

    def day_totals(self, day=None):
        """Water oz, electrolyte and caffeine servings for one day."""
        day = day or dt.date.today()
        rows = self.between(day, day + dt.timedelta(days=1))
        totals = {"water": 0.0, "electrolytes": 0.0, "caffeine": 0.0}
        for _, cat, val, _ in rows:
            if cat == "water":
                totals["water"] += water_ounces(val)
            elif cat in totals:
                totals[cat] += servings(val)
        return totals

    def water_today(self):
        return self.day_totals()["water"]

    def rescue_days(self, year, month):
        """Distinct days this calendar month with a rescue med logged."""
        start = dt.date(year, month, 1)
        end = dt.date(year + month // 12, month % 12 + 1, 1)
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(DISTINCT substr(logged_at, 1, 10)) FROM entries"
                " WHERE category = 'rescue_meds' AND logged_at >= ? AND logged_at < ?",
                (str(start), str(end))).fetchone()
        return row[0]

    def export_csv(self, path):
        with self._conn() as c:
            rows = c.execute("SELECT logged_at, category, value, severity, source"
                             " FROM entries ORDER BY logged_at, id").fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["logged_at", "category", "value", "severity", "source"])
            w.writerows(rows)
        return len(rows)

    # ---- reminders and day modes -----------------------------------------

    def reminder_sent(self, slot):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM reminders_sent WHERE slot = ?",
                             (slot,)).fetchone() is not None

    def record_reminder(self, slot):
        with self._conn() as c, c:
            c.execute("INSERT OR IGNORE INTO reminders_sent VALUES (?, ?)", (slot, _now()))

    def day_mode(self, day=None):
        day = str(day or dt.date.today())
        with self._conn() as c:
            row = c.execute("SELECT mode FROM day_modes WHERE day = ?", (day,)).fetchone()
        return row[0] if row else "normal"

    def set_day_mode(self, mode, day=None):
        day = str(day or dt.date.today())
        with self._conn() as c, c:
            if mode == "normal":
                c.execute("DELETE FROM day_modes WHERE day = ?", (day,))
            else:
                c.execute("INSERT OR REPLACE INTO day_modes VALUES (?, ?)", (day, mode))

    # ---- weather and pollen ----------------------------------------------

    def save_weather(self, days):
        with self._conn() as c, c:
            c.executemany(
                "INSERT OR REPLACE INTO weather VALUES (:day, :temp_max, :temp_min, :humidity,"
                " :pressure_mean, :pressure_min, :pressure_max, :precip, :fetched_at)",
                [dict(d, fetched_at=_now()) for d in days])

    def weather(self, start, end):
        """{day: row dict} for start <= day <= end."""
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM weather WHERE day >= ? AND day <= ?",
                             (str(start), str(end))).fetchall()
        return {r["day"]: dict(r) for r in rows}

    def weather_fetched_at(self, day=None):
        day = str(day or dt.date.today())
        with self._conn() as c:
            row = c.execute("SELECT fetched_at FROM weather WHERE day = ?", (day,)).fetchone()
        return dt.datetime.fromisoformat(row[0]) if row else None

    def save_pollen(self, day, summary, raw):
        with self._conn() as c, c:
            c.execute("INSERT OR REPLACE INTO pollen VALUES (?, ?, ?, ?)",
                      (str(day), summary, raw, _now()))

    def pollen(self, start, end):
        with self._conn() as c:
            rows = c.execute("SELECT day, summary FROM pollen WHERE day >= ? AND day <= ?",
                             (str(start), str(end))).fetchall()
        return dict(rows)
