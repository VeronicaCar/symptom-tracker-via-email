"""Settings stored in config.json next to the app. No passwords live here."""

import json

from . import APP_DIR
from .parser import DEFAULT_CODES

CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "symptom_log.db"
LOG_PATH = APP_DIR / "tracker.log"

DEFAULTS = {
    "tracker_email": "",            # the dedicated Gmail the app reads and sends from
    "allowed_senders": [],          # only mail from these addresses is logged
    "reminder_to": "",              # where check-in reminders go
    "reminder_times": ["10:00", "13:00", "16:00"],
    "reminder_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "poll_minutes": 5,
    "reply_to_logs": "errors",      # "always", "errors" (unreadable emails only) or "never"
    "skip_if_logged_minutes": 60,   # skip a reminder if something was logged this recently
    "water_goal_oz": 64,
    "summary_enabled": True,        # weekly summary email
    "summary_day": "Sun",
    "summary_time": "18:00",
    "weather_place": "",            # ZIP code or "City, ST"; blank turns weather off
    "weather_lat": None,
    "weather_lon": None,
    "weather_label": "",
    "pollen_senders": [],           # addresses or domains of pollen report emails
    "short_codes": dict(DEFAULT_CODES),
    "imap_host": "imap.gmail.com",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    for key in ("allowed_senders", "pollen_senders"):
        cfg[key] = [a.strip().lower() for a in cfg[key] if a.strip()]
    return cfg


def codes_to_text(codes):
    return "\n".join(f"{k} = {v}" for k, v in codes.items())


def codes_from_text(text):
    """Parse 'w = water: {n}oz' lines. Raises ValueError on a bad line."""
    from .parser import category_for
    codes = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        code, sep, spec = line.partition("=")
        code, spec = code.strip().lower(), spec.strip()
        cat, colon, tmpl = spec.partition(":")
        if not sep or not colon or not code.isalpha() or not category_for(cat):
            raise ValueError(f"Short code line not understood: {line.strip()!r}\n"
                             "Use the form: w = water: {n}oz")
        if "{n}" not in tmpl and "{text}" not in tmpl:
            raise ValueError(f"Short code {code!r} needs {{n}} or {{text}} in it")
        codes[code] = f"{cat.strip()}: {tmpl.strip()}"
    return codes


def save(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def is_configured(cfg):
    return bool(cfg["tracker_email"] and cfg["allowed_senders"] and cfg["reminder_to"])
