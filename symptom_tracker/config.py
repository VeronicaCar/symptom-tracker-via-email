"""Settings stored in config.json next to the app. No passwords live here."""

import json

from . import APP_DIR
from . import parser
from .parser import DEFAULT_CODES

CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "symptom_log.db"
LOG_PATH = APP_DIR / "tracker.log"

_FIRST_CODES = ["w", "e", "c", "m", "d", "v", "n", "s", "r"]  # built-ins before this was tracked

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
    "caffeine_drinks": {"monster": 150},   # mg per drink (Monster Ultra Sunrise can)
    "default_codes_seen": list(DEFAULT_CODES),  # so new built-in codes get added once
    "imap_host": "imap.gmail.com",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    cfg.update(saved)
    for key in ("allowed_senders", "pollen_senders"):
        cfg[key] = [a.strip().lower() for a in cfg[key] if a.strip()]
    # Offer built-in codes added in later versions, without bringing back
    # ones the user deleted.
    seen = set(saved.get("default_codes_seen", _FIRST_CODES if saved else DEFAULT_CODES))
    for code, spec in DEFAULT_CODES.items():
        if code not in seen and code not in cfg["short_codes"]:
            cfg["short_codes"][code] = spec
    cfg["default_codes_seen"] = sorted(seen | set(DEFAULT_CODES))
    parser.CAFFEINE_MG.clear()
    parser.CAFFEINE_MG.update(cfg["caffeine_drinks"])
    return cfg


def drinks_to_text(drinks):
    return ", ".join(f"{name} = {mg:g}" for name, mg in drinks.items())


def drinks_from_text(text):
    """'monster = 150, red bull = 80' -> {'monster': 150.0, 'red bull': 80.0}."""
    drinks = {}
    for part in text.split(","):
        if not part.strip():
            continue
        name, sep, mg = part.partition("=")
        try:
            if not sep or not name.strip():
                raise ValueError
            drinks[name.strip().lower()] = float(mg.strip().lower().removesuffix("mg"))
        except ValueError:
            raise ValueError(f"Caffeine per drink not understood: {part.strip()!r}\n"
                             "Use the form: monster = 150") from None
    return drinks


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
