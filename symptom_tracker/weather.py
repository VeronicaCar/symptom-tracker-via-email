"""Daily weather from Open-Meteo (free, no account) and pollen email parsing."""

import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

HPA_TO_INHG = 0.02953


def _get(url, params):
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=20) as r:
        return json.load(r)


def geocode(place):
    """'10001', 'Springfield, IL' or 'Springfield' -> (lat, lon, 'Springfield, Illinois')."""
    place = place.strip()
    name, _, region = (p.strip() for p in place.partition(","))
    params = {"name": name, "count": 10, "language": "en", "format": "json"}
    if re.fullmatch(r"\d{5}", name):
        params["countryCode"] = "US"
    results = _get(GEOCODE_URL, params).get("results") or []
    if region:
        want = US_STATES.get(region.upper(), region).lower()
        results = [r for r in results if want in (r.get("admin1", "").lower(),
                                                  r.get("country", "").lower(),
                                                  r.get("country_code", "").lower())] or results
    if not results:
        raise ValueError(f"Couldn't find {place!r}. Try a nearby ZIP code or \"City, ST\".")
    r = results[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1")) if x)
    return r["latitude"], r["longitude"], label


def fetch_daily(lat, lon, past_days=30):
    """Daily weather rows for the last past_days days plus today."""
    data = _get(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "past_days": min(past_days, 92), "forecast_days": 1,
        "hourly": "pressure_msl,relative_humidity_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
    })
    hourly = defaultdict(lambda: {"p": [], "h": []})
    h = data["hourly"]
    for t, p, rh in zip(h["time"], h["pressure_msl"], h["relative_humidity_2m"]):
        day = t[:10]
        if p is not None:
            hourly[day]["p"].append(p)
        if rh is not None:
            hourly[day]["h"].append(rh)
    d = data["daily"]
    rows = []
    for i, day in enumerate(d["time"]):
        p, rh = hourly[day]["p"], hourly[day]["h"]
        rows.append({
            "day": day,
            "temp_max": d["temperature_2m_max"][i],
            "temp_min": d["temperature_2m_min"][i],
            "precip": d["precipitation_sum"][i],
            "humidity": round(sum(rh) / len(rh), 1) if rh else None,
            "pressure_mean": round(sum(p) / len(p), 1) if p else None,
            "pressure_min": min(p) if p else None,
            "pressure_max": max(p) if p else None,
        })
    return rows


def pressure_change(today, yesterday):
    """Change in mean pressure (hPa) from the day before, or None."""
    if today and yesterday and today.get("pressure_mean") and yesterday.get("pressure_mean"):
        return round(today["pressure_mean"] - yesterday["pressure_mean"], 1)
    return None


def describe(w, change=None):
    """Short one-line description of a weather row."""
    if not w:
        return ""
    parts = []
    if w.get("temp_max") is not None:
        parts.append(f"{w['temp_min']:.0f}–{w['temp_max']:.0f}°F")
    if w.get("pressure_mean") is not None:
        s = f"{w['pressure_mean'] * HPA_TO_INHG:.2f} inHg"
        if change is not None and abs(change) >= 1:
            s += f" ({'down' if change < 0 else 'up'} {abs(change):.0f} hPa)"
        parts.append(s)
    if w.get("humidity") is not None:
        parts.append(f"{w['humidity']:.0f}% humidity")
    if w.get("precip"):
        parts.append(f"{w['precip']:.2f}\" rain")
    return ", ".join(parts)


# ---- pollen emails -------------------------------------------------------

_POLLEN_WORDS = re.compile(r"\b(tree|grass|weed|ragweed|mold|mould|pollen|allerg\w*|oak|birch|"
                           r"maple|cedar|pine|elm)\b", re.I)
_LEVEL_WORDS = re.compile(r"\b(none|absent|very low|low|low-medium|moderate|medium|"
                          r"medium-high|high|very high|extreme|\d+(\.\d+)?)\b", re.I)


_POLLEN_LEVEL = re.compile(r"^(none|absent|very low|low|low-medium|medium|moderate|medium-high|high|"
                           r"very high|extreme)$", re.I)
_BOILERPLATE = re.compile(r"copyright|unsubscribe|privacy|terms of use|all rights reserved|sent by",
                          re.I)


def _pollen_com(lines):
    """Pollen.com Allergy Alert: 'TODAY / 4.60 / Low-Medium / Today's Top Allergens: ...'."""
    def day(label):
        if label not in lines:
            return None
        i = lines.index(label)
        num = next((l for l in lines[i + 1:i + 4] if re.fullmatch(r"\d+(\.\d+)?", l)), None)
        level = next((l for l in lines[i + 1:i + 5] if _POLLEN_LEVEL.match(l)), None)
        return f"{float(num):g} {level}" if num and level else level

    today = day("TODAY")
    if not today:
        return None
    allergens = []
    if "Today's Top Allergens:" in lines:
        for l in lines[lines.index("Today's Top Allergens:") + 1:]:
            if l.endswith(":") or l.lower().startswith(("how will", "5 day", "the next")):
                break
            allergens.append(l)
    summary = f"{today} ({', '.join(allergens[:4])})" if allergens else today
    tomorrow = day("TOMORROW")
    return summary + (f"; tomorrow {tomorrow}" if tomorrow else "")


def pollen_summary(subject, text):
    """Short summary of a pollen alert email: pollen.com's format first, else
    lines that name a pollen type and a level."""
    lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
    special = _pollen_com(lines)
    if special:
        return special
    picked = []
    for line in lines:
        if line.startswith(">") or len(line) > 160 or _BOILERPLATE.search(line):
            continue
        if _POLLEN_WORDS.search(line) and _LEVEL_WORDS.search(line) and line not in picked:
            picked.append(line)
        if len(picked) >= 6:
            break
    return "; ".join(picked) if picked else (subject or "").strip()
