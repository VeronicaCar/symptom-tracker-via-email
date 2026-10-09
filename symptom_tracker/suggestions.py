"""Ideas for what might help, by symptom and severity. Mirrors SUGGESTIONS in
google_apps_script/Reminders.gs; keep the two in step."""

import datetime as dt
import re

MIGRAINE_TIPS = ["mint gum", "your menthol head stick", "migraine glasses", "a walk loop",
                 "electrolytes"]
RULES = [
    {"name": "Sinus pain", "match": re.compile(r"sinus|congest", re.I), "category": "sinus",
     "at": 2, "tips": ["an Advil", "more water"], "join": "and"},
    {"name": "Migraine", "match": re.compile(r"migraine|headache", re.I),
     "at": 2, "tips": MIGRAINE_TIPS, "strong_at": 3.5, "strong_tip": "a Nurtec"},
    {"name": "Dizziness", "match": re.compile(r"dizz|vertigo|light-?headed", re.I),
     "at": 2, "tips": MIGRAINE_TIPS, "strong_at": 3.5, "strong_tip": "a Dramamine Less-Drowsy"},
]
_SEV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*10\b")


def _list(items, joiner):
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + ("," if len(items) > 2 else "") + f" {joiner} {items[-1]}"


def severities(entries):
    """Latest severity per rule from (category, value) pairs in time order."""
    found = {}
    for category, value in entries:
        if category not in ("symptoms", "sinus"):
            continue
        for part in re.split(r"[,;]", value):
            m = _SEV_RE.search(part)
            if not m:
                continue
            for rule in RULES:
                if rule["match"].search(part) or rule.get("category") == category:
                    found[rule["name"]] = float(m.group(1))
    return found


def ideas(found, rescue_days=0, advil_days=0):
    out = []
    for rule in RULES:
        level = found.get(rule["name"])
        if level is None or level < rule["at"]:
            continue
        line = f"{rule['name']} {level:g}/10: try {_list(rule['tips'], rule.get('join', 'or'))}."
        if rule.get("strong_at") and level >= rule["strong_at"]:
            line += (f" Since it's {rule['strong_at']:g} or higher, this may be a good time for "
                     f"{rule['strong_tip']}.")
            if rescue_days >= 8:
                line += f" (Rescue meds have been needed on {rescue_days} days this month.)"
        if any("advil" in t.lower() for t in rule["tips"]) and advil_days >= 12:
            line += f" (Advil on {advil_days} days this month already.)"
        out.append(line)
    return out


def for_today(store, day=None):
    """Ideas based on the latest severities logged today."""
    day = day or dt.date.today()
    rows = store.between(day, day + dt.timedelta(days=1))
    found = severities([(cat, value) for _, cat, value, _ in rows])
    return ideas(found, store.rescue_days(day.year, day.month),
                 store.days_with("advil", day.year, day.month))
