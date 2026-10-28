"""Turn a day's entries into what the Journal and Charts tabs show.

Kept free of Tk so it can be tested: the app draws whatever these return.
"""

import datetime as dt
import re

from .parser import LABELS, severity_of
from .store import water_ounces

# Which line a rated symptom goes on in the chart.
SERIES = [("Sinus", re.compile(r"sinus|congest", re.I)),
          ("Migraine", re.compile(r"migraine|headache", re.I)),
          ("Dizzy", re.compile(r"dizz|vertigo|light-?headed", re.I)),
          ("Fatigue", re.compile(r"fatigu|tired|exhaust", re.I)),
          ("Nausea", re.compile(r"nause", re.I))]

# Tag colors by kind; theme.py maps these names to Kimbie Dark colors.
KIND = {"water": "water", "food": "food", "caffeine": "caffeine", "electrolytes": "water",
        "symptoms": "symptom", "sinus": "symptom", "fatigue": "symptom",
        "rescue_meds": "med", "advil": "med"}


def series_for(category, value):
    """Chart line name for a rated entry, e.g. ('sinus', '2/10') -> 'Sinus'."""
    if category == "sinus":
        return "Sinus"
    if category == "fatigue":
        return "Fatigue"
    for name, pattern in SERIES:
        if pattern.search(value):
            return name
    return "Other"


def _time(when):
    return when.strftime("%I:%M %p").lstrip("0")


def _tag_text(category, value):
    if category == "water":
        return "Water " + (value.replace("oz", " oz") if re.fullmatch(r"\d+(\.\d+)?oz", value) else value)
    if category in ("symptoms",):
        return value[:1].upper() + value[1:]
    if category in ("sinus", "fatigue") and re.fullmatch(r"\d+(\.\d+)?/10", value):
        return f"{LABELS[category]} {value}"
    if category == "rescue_meds":
        return f"Rescue · {value}"
    if category == "advil":
        return f"Advil · {value}"
    return f"{LABELS.get(category, category)} · {value}"


def join_notes(notes):
    """Notes logged together, read as one paragraph: 'Slept in. Sinuses feel full'."""
    out = ""
    for note in notes:
        if out:
            out += (" " if out[-1] in ".!?)" else ". ")
        out += note
    return out


def day_view(rows):
    """rows: (logged_at, category, value, severity), oldest first, for one day.

    Returns {"groups": [{"time", "notes": [...], "tags": [(kind, text)]}],
             "series": {name: [(hour, severity)]}, "water": [(hour, total oz)],
             "peaks": {name: severity}}. Entries logged in the same minute are one group.
    """
    groups, series, water, peaks = [], {}, [], {}
    total = 0.0
    for logged_at, category, value, severity in rows:
        when = dt.datetime.fromisoformat(logged_at)
        stamp = _time(when)
        if not groups or groups[-1]["time"] != stamp:
            groups.append({"time": stamp, "notes": [], "tags": []})
        group = groups[-1]
        hour = when.hour + when.minute / 60
        rated = severity if severity is not None else (
            severity_of(value) if category in ("symptoms", "sinus", "fatigue") else None)
        if category == "misc" or (category == "symptoms" and rated is None):
            group["notes"].append(value[:1].upper() + value[1:])
            continue
        if rated is not None:
            name = series_for(category, value)
            series.setdefault(name, []).append((hour, float(rated)))
            peaks[name] = max(peaks.get(name, 0), float(rated))
        if category == "water":
            total += water_ounces(value)
            water.append((hour, total))
        group["tags"].append((KIND.get(category, "other"), _tag_text(category, value)))
    return {"groups": groups, "series": series, "water": water, "peaks": peaks}


def day_blurb(rows):
    """A few words for the day list: 'Migraine 3 · 48 oz'."""
    view = day_view(rows)
    bits = []
    if view["peaks"]:
        name, worst = max(view["peaks"].items(), key=lambda kv: kv[1])
        bits.append(f"{name} {worst:g}")
    if view["water"]:
        bits.append(f"{view['water'][-1][1]:.0f} oz")
    elif view["groups"] and view["groups"][0]["notes"]:
        bits.append(view["groups"][0]["notes"][0][:22])
    return " · ".join(bits)


def peak_of_day(rows):
    """Worst rating of the day, or None if nothing was rated."""
    peaks = day_view(rows)["peaks"]
    return max(peaks.values()) if peaks else None
