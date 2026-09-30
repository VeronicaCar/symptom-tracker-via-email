"""Weekly summary email and printable doctor visit report."""

import datetime as dt
import re
from collections import Counter
from html import escape

from . import weather as wx
from .store import servings, water_ounces

MIGRAINE_RE = re.compile(r"migraine|headache|aura", re.I)
DIZZY_RE = re.compile(r"dizz|vertigo|light-?headed|presyncope|faint", re.I)
HIGH_POLLEN_RE = re.compile(r"\b(high|very high|extreme)\b", re.I)
PRESSURE_DROP = -5  # hPa day-over-day that counts as a notable drop

DAY = dt.timedelta(days=1)


def _dates(start, end):
    d = start
    while d <= end:
        yield d
        d += DAY


def collect(store, start, end):
    """Per-day aggregates for start..end (dates, inclusive)."""
    weather = store.weather(start - DAY, end)
    pollen = store.pollen(start, end)
    days = {d: {"date": d, "symptoms": [], "sinus": [], "rescue_meds": [], "food": [],
                "misc": [], "water": 0.0, "electrolytes": 0.0, "caffeine": 0.0,
                "worst": None, "sinus_worst": None, "migraine": False, "dizzy": False,
                "logged": False}
            for d in _dates(start, end)}
    for logged_at, cat, value, sev in store.between(start, end + DAY):
        d = days.get(dt.date.fromisoformat(logged_at[:10]))
        if d is None:
            continue
        d["logged"] = True
        if cat == "water":
            d["water"] += water_ounces(value)
        elif cat in ("electrolytes", "caffeine"):
            d[cat] += servings(value)
        elif cat in d:
            d[cat].append(value)
        if cat == "symptoms":
            if sev is not None:
                d["worst"] = max(d["worst"] or 0, sev)
            d["migraine"] |= bool(MIGRAINE_RE.search(value))
            d["dizzy"] |= bool(DIZZY_RE.search(value))
        if cat == "sinus" and sev is not None:
            d["sinus_worst"] = max(d["sinus_worst"] or 0, sev)
    for day, d in days.items():
        w = weather.get(str(day))
        d["weather"] = w
        d["pressure_change"] = wx.pressure_change(w, weather.get(str(day - DAY)))
        d["pollen"] = pollen.get(str(day), "")
    return list(days.values())


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def stats(days, water_goal):
    sym = [d for d in days if d["symptoms"]]
    return {
        "days": len(days),
        "logged": sum(d["logged"] for d in days),
        "symptom_days": len(sym),
        "migraine_days": sum(d["migraine"] for d in days),
        "dizzy_days": sum(d["dizzy"] for d in days),
        "sinus_days": sum(bool(d["sinus"]) for d in days),
        "rescue_days": sum(bool(d["rescue_meds"]) for d in days),
        "avg_worst": _avg([d["worst"] for d in days]),
        "avg_water": _avg([d["water"] for d in days if d["logged"]]),
        "water_goal_days": sum(d["water"] >= water_goal for d in days),
        "avg_electrolytes": _avg([d["electrolytes"] for d in days if d["logged"]]),
        "avg_caffeine": _avg([d["caffeine"] for d in days if d["logged"]]),
        "pressure_drop_days": [d for d in days if (d["pressure_change"] or 0) <= PRESSURE_DROP],
        "high_pollen_days": [d for d in days if HIGH_POLLEN_RE.search(d["pollen"])],
    }


def _fmt(v, digits=0, suffix=""):
    return "–" if v is None else f"{v:.{digits}f}{suffix}"


def _short_date(d):
    return d.strftime("%a %b ") + str(d.day)


def _rescue_line(store, today):
    n = store.rescue_days(today.year, today.month)
    line = f"Rescue meds this month: {n} of 10 days"
    if n >= 8:
        line += "  ⚠ close to the 10-day limit for rebound headaches"
    return line, n


# ---- weekly summary ----------------------------------------------------------

def weekly_summary(cfg, store, end=None):
    """(subject, text, html) for the 7 days ending on `end` (default today)."""
    end = end or dt.date.today()
    start = end - 6 * DAY
    goal = cfg.get("water_goal_oz", 64)
    days = collect(store, start, end)
    s = stats(days, goal)
    prev = stats(collect(store, start - 7 * DAY, start - DAY), goal)
    rescue_line, _ = _rescue_line(store, dt.date.today())

    def delta(now, before):
        diff = now - before
        return "same as last week" if diff == 0 else (
            f"{abs(diff)} {'more' if diff > 0 else 'fewer'} than last week")

    worst = max((d for d in days if d["worst"] is not None), key=lambda d: d["worst"], default=None)
    lines = [
        f"Symptom days: {s['symptom_days']} of 7",
        f"Migraine/headache days: {s['migraine_days']} ({delta(s['migraine_days'], prev['migraine_days'])})",
        f"Dizzy/vertigo days: {s['dizzy_days']} ({delta(s['dizzy_days'], prev['dizzy_days'])})",
        f"Sinus pain days: {s['sinus_days']}",
        f"Average worst severity: {_fmt(s['avg_worst'], 1, '/10')}"
        + (f" (worst: {_short_date(worst['date'])}, {worst['worst']}/10)" if worst else ""),
        f"Rescue med days this week: {s['rescue_days']}",
        rescue_line,
        f"Water: {_fmt(s['avg_water'])} oz/day on average, goal of {goal} oz hit on "
        f"{s['water_goal_days']} of 7 days",
        f"Electrolytes: {_fmt(s['avg_electrolytes'], 1)}/day   Caffeine: {_fmt(s['avg_caffeine'], 1)}/day",
    ]
    if s["pressure_drop_days"]:
        lines.append("Big pressure drops: " + ", ".join(
            f"{_short_date(d['date'])} ({d['pressure_change']:+.0f} hPa)" for d in s["pressure_drop_days"]))
    if s["high_pollen_days"]:
        lines.append("High pollen: " + ", ".join(_short_date(d["date"]) for d in s["high_pollen_days"]))

    subject = f"Your week: {start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}"
    text = subject + "\n\n" + "\n".join(lines) + "\n"

    cell = "padding:6px 8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top"
    rows = "".join(
        f"<tr><td style='{cell}'>{_short_date(d['date'])}</td>"
        f"<td style='{cell}'>{escape('; '.join(d['symptoms'] + d['sinus'])) or '–'}</td>"
        f"<td style='{cell}'>{_fmt(d['water'] or None, 0, ' oz')}</td>"
        f"<td style='{cell}'>{escape(', '.join(d['rescue_meds'])) or '–'}</td>"
        f"<td style='{cell}'>{escape(wx.describe(d['weather'], d['pressure_change'])) or '–'}"
        + (f"<br><span style='color:#666'>Pollen: {escape(d['pollen'])}</span>" if d['pollen'] else "")
        + "</td></tr>"
        for d in days)
    html = (
        "<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1c1c1c'>"
        f"<h2 style='margin:0 0 8px'>{escape(subject)}</h2>"
        "<ul style='padding-left:18px;line-height:1.6'>"
        + "".join(f"<li>{escape(l)}</li>" for l in lines) + "</ul>"
        "<table style='border-collapse:collapse;font-size:13px'>"
        f"<tr><th style='{cell}'>Day</th><th style='{cell}'>Symptoms</th><th style='{cell}'>Water</th>"
        f"<th style='{cell}'>Rescue meds</th><th style='{cell}'>Weather</th></tr>"
        + rows + "</table></div>")
    return subject, text, html


# ---- doctor visit report ------------------------------------------------------

def _months(days):
    groups = {}
    for d in days:
        groups.setdefault((d["date"].year, d["date"].month), []).append(d)
    return groups


def _symptom_counts(days):
    c = Counter()
    for d in days:
        seen = set()
        for v in d["symptoms"]:
            name = re.sub(r"\b\d+(\.\d+)?\s*/\s*10\b|[:\d]+", "", v.lower()).strip(" ,.-")
            name = " ".join(name.split()[:3])
            if name and name not in seen:
                seen.add(name)
                c[name] += 1
    return c.most_common(10)


def _pattern(days, flag, label):
    """Compare how often symptom days vs other days had some condition."""
    sym = [d for d in days if d["migraine"] or d["dizzy"] or (d["worst"] or 0) >= 5]
    other = [d for d in days if d["logged"] and d not in sym]
    if len(sym) < 3 or len(other) < 3:
        return None
    a = sum(map(flag, sym)) / len(sym)
    b = sum(map(flag, other)) / len(other)
    return f"{label}: {a:.0%} of bad days vs {b:.0%} of other logged days"


def _chart(days, goal):
    w, h, pad = 900, 200, 30
    n = len(days)
    bw = (w - 2 * pad) / max(n, 1)
    parts = [f"<svg viewBox='0 0 {w} {h + 60}' width='100%' role='img' "
             "aria-label='Daily worst severity and water'>"]
    for i in range(0, 11, 5):
        y = h - i / 10 * (h - 20)
        parts.append(f"<line x1='{pad}' x2='{w - pad}' y1='{y:.0f}' y2='{y:.0f}' stroke='#e3e3e3'/>"
                     f"<text x='{pad - 6}' y='{y + 4:.0f}' font-size='10' text-anchor='end' fill='#777'>{i}</text>")
    for i, d in enumerate(days):
        x = pad + i * bw
        if d["worst"] is not None:
            bh = d["worst"] / 10 * (h - 20)
            color = "#c0392b" if d["worst"] >= 7 else "#e67e22" if d["worst"] >= 4 else "#f1c40f"
            parts.append(f"<rect x='{x + 1:.1f}' y='{h - bh:.1f}' width='{max(bw - 2, 1):.1f}' "
                         f"height='{bh:.1f}' fill='{color}'><title>{d['date']}: {d['worst']}/10</title></rect>")
        if d["rescue_meds"]:
            parts.append(f"<circle cx='{x + bw / 2:.1f}' cy='{h + 12}' r='4' fill='#8e44ad'>"
                         f"<title>{d['date']}: {escape(', '.join(d['rescue_meds']))}</title></circle>")
        if d["water"] and goal:
            ratio = min(d["water"] / goal, 1)
            parts.append(f"<rect x='{x + 1:.1f}' y='{h + 24}' width='{max(bw - 2, 1):.1f}' height='10' "
                         f"fill='#2e86c1' fill-opacity='{0.15 + 0.85 * ratio:.2f}'>"
                         f"<title>{d['date']}: {d['water']:.0f} oz</title></rect>")
        if n <= 14 or (d["date"].weekday() == 0 if n <= 60 else d["date"].day == 1):
            parts.append(f"<text x='{x + bw / 2:.1f}' y='{h + 52}' font-size='9' text-anchor='middle' "
                         f"fill='#777'>{d['date'].month}/{d['date'].day}</text>")
    parts.append("</svg>")
    return "".join(parts)


def doctor_report(cfg, store, start, end):
    goal = cfg.get("water_goal_oz", 64)
    days = collect(store, start, end)
    s = stats(days, goal)

    month_rows = ""
    for (y, m), md in _months(days).items():
        ms = stats(md, goal)
        month_rows += (
            f"<tr><td>{dt.date(y, m, 1).strftime('%b %Y')}</td><td>{ms['logged']}/{ms['days']}</td>"
            f"<td>{ms['symptom_days']}</td><td>{ms['migraine_days']}</td><td>{ms['dizzy_days']}</td>"
            f"<td>{ms['sinus_days']}</td><td>{_fmt(ms['avg_worst'], 1)}</td>"
            f"<td><b>{ms['rescue_days']}</b></td><td>{_fmt(ms['avg_water'])}</td></tr>")

    meds = Counter(v.lower() for d in days for v in d["rescue_meds"])
    patterns = [p for p in (
        _pattern(days, lambda d: any((x["pressure_change"] or 0) <= PRESSURE_DROP
                                     for x in days if x["date"] in (d["date"], d["date"] - DAY)),
                 f"Pressure drop of 5+ hPa that day or the day before"),
        _pattern(days, lambda d: d["water"] < goal, f"Under {goal} oz of water"),
        _pattern(days, lambda d: bool(HIGH_POLLEN_RE.search(d["pollen"])), "High pollen"),
        _pattern(days, lambda d: d["caffeine"] >= 3, "3+ caffeine servings"),
    ) if p]

    def cell(items):
        return escape("; ".join(items)) or "<span class='dim'>–</span>"

    daily_rows = "".join(
        f"<tr><td class='nowrap'>{_short_date(d['date'])}</td>"
        f"<td>{cell(d['symptoms'])}</td><td>{cell(d['sinus'])}</td><td>{cell(d['rescue_meds'])}</td>"
        f"<td class='num'>{_fmt(d['water'] or None, 0)}</td>"
        f"<td class='num'>{_fmt(d['electrolytes'] or None, 0)}</td>"
        f"<td class='num'>{_fmt(d['caffeine'] or None, 0)}</td>"
        f"<td>{escape(wx.describe(d['weather'], d['pressure_change']))}"
        + (f"<br><span class='dim'>Pollen: {escape(d['pollen'])}</span>" if d['pollen'] else "")
        + f"</td><td>{cell(d['food'] + d['misc'])}</td></tr>"
        for d in reversed(days) if d["logged"])

    top = "".join(f"<li>{escape(name)} <span class='dim'>({n} days)</span></li>"
                  for name, n in _symptom_counts(days))
    med_list = "".join(f"<li>{escape(name)} <span class='dim'>(×{n})</span></li>"
                       for name, n in meds.most_common(8))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Symptom report {start} to {end}</title>
<style>
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1c1c1c; background: #fff;
         max-width: 1000px; margin: 24px auto; padding: 0 16px; font-size: 14px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 28px 0 8px; border-bottom: 2px solid #2f6f5e; padding-bottom: 4px; }}
  .dim {{ color: #777; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
  .kpi {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px 12px; }}
  .kpi b {{ display: block; font-size: 22px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #e3e3e3; padding: 5px 6px; text-align: left; vertical-align: top; }}
  th {{ background: #f3f5f4; }}
  .num {{ text-align: right; }} .nowrap {{ white-space: nowrap; }}
  .legend span {{ margin-right: 14px; }}
  .swatch {{ display: inline-block; width: 10px; height: 10px; margin-right: 4px; vertical-align: middle; }}
  @media print {{ body {{ margin: 0; }} h2 {{ break-after: avoid; }} tr {{ break-inside: avoid; }} }}
</style></head><body>
<h1>Symptom report</h1>
<div class="dim">{start.strftime('%B %d, %Y')} – {end.strftime('%B %d, %Y')} · generated {dt.date.today().strftime('%B %d, %Y')}</div>

<h2>Overview</h2>
<div class="kpis">
  <div class="kpi"><b>{s['migraine_days']}</b>migraine/headache days</div>
  <div class="kpi"><b>{s['dizzy_days']}</b>dizzy/vertigo days</div>
  <div class="kpi"><b>{s['symptom_days']}</b>days with any symptom</div>
  <div class="kpi"><b>{s['rescue_days']}</b>rescue medication days</div>
  <div class="kpi"><b>{_fmt(s['avg_worst'], 1)}</b>average worst severity (0–10)</div>
  <div class="kpi"><b>{_fmt(s['avg_water'])} oz</b>average water per day</div>
</div>
<p class="dim">Days with at least one entry: {s['logged']} of {s['days']}. Days without entries are not counted as symptom-free.</p>

<h2>Daily worst severity</h2>
<div class="legend dim">
  <span><i class="swatch" style="background:#f1c40f"></i>1–3</span>
  <span><i class="swatch" style="background:#e67e22"></i>4–6</span>
  <span><i class="swatch" style="background:#c0392b"></i>7–10</span>
  <span><i class="swatch" style="background:#8e44ad;border-radius:50%"></i>rescue med taken</span>
  <span><i class="swatch" style="background:#2e86c1"></i>water (darker = closer to {goal} oz)</span>
</div>
{_chart(days, goal)}

<h2>By month</h2>
<table><tr><th>Month</th><th>Days logged</th><th>Symptom days</th><th>Migraine / headache</th>
<th>Dizzy / vertigo</th><th>Sinus pain</th><th>Avg worst severity</th><th>Rescue med days</th>
<th>Avg water (oz)</th></tr>{month_rows}</table>

<h2>Most frequent symptoms</h2>
<ul>{top or '<li class="dim">None logged</li>'}</ul>

<h2>Rescue medications</h2>
<ul>{med_list or '<li class="dim">None logged</li>'}</ul>

<h2>Possible patterns</h2>
<p class="dim">Simple comparisons of days with a migraine, dizziness or severity 5+ against other logged days. Patterns, not conclusions.</p>
<ul>{''.join(f'<li>{escape(p)}</li>' for p in patterns) or '<li class="dim">Not enough data yet</li>'}</ul>

<h2>Daily log</h2>
<table><tr><th>Date</th><th>Symptoms</th><th>Sinus</th><th>Rescue meds</th><th>Water (oz)</th>
<th>Electrolytes</th><th>Caffeine</th><th>Weather</th><th>Food &amp; notes</th></tr>{daily_rows}</table>
</body></html>
"""
