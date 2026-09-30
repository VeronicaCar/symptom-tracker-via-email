"""Turn an email's subject and body into log entries.

Shapes understood:

* One-off: the subject starts with a category word, e.g. ``WATER 16oz``,
  ``Symptom: headache 6/10`` or ``MIGRAINE 6/10``. If the subject has no
  value, the first line of the body is used.
* Short codes: the subject (or a body line) is made of codes such as
  ``w16 m7`` = 16oz water + migraine 7/10. Codes are configurable.
* Full log: any other subject (``LOG``, a reply to a check-in reminder, ...).
  Every ``Category: value`` line and every short-code line in the body
  becomes an entry. Blank values are skipped.
* Commands: ``ROUGH DAY``, ``PAUSE``, ``RESUME``, ``SUMMARY``.

Anything can be backdated by ending it with ``@time``: ``WATER 16oz @2pm``,
``m6 @yesterday 4pm``, or ``LOG @noon`` for a whole email.
"""

import datetime as dt
import html
import re
from typing import NamedTuple, Optional

CATEGORIES = ("symptoms", "sinus", "water", "electrolytes", "caffeine", "food",
              "rescue_meds", "misc")
LABELS = {"symptoms": "Symptoms", "sinus": "Sinus pain", "water": "Water",
          "electrolytes": "Electrolytes", "caffeine": "Caffeine", "food": "Food",
          "rescue_meds": "Rescue meds", "misc": "Misc"}
SEVERITY_CATEGORIES = {"symptoms", "sinus"}

# Generic names just pick the category; every other alias is kept in the
# logged value ("MIGRAINE 6/10" logs "migraine 6/10" under Symptoms).
_GENERIC = {
    "symptoms": ("symptom", "symptoms", "sym", "sx", "feeling"),
    "sinus": ("sinus", "sinuses", "sinus pain"),
    "water": ("water", "h2o", "drink", "drank", "fluid", "fluids"),
    "electrolytes": ("electrolytes", "electrolyte", "lytes"),
    "caffeine": ("caffeine",),
    "food": ("food", "ate", "eat", "meal"),
    "rescue_meds": ("rescue", "rescue med", "rescue meds", "rescue medication", "med",
                    "meds", "medication"),
    "misc": ("misc", "miscellaneous", "note", "notes", "other"),
}
_LABELLED = {
    "symptoms": ("pain", "migraine", "headache", "dizzy", "dizziness", "vertigo", "nausea",
                 "nauseous", "fatigue", "tired", "brain fog", "brainfog", "lightheaded",
                 "presyncope", "aura"),
    "sinus": ("congestion", "congested", "allergies", "allergy"),
    "water": (),
    "electrolytes": ("salt", "salt tabs", "sodium", "lmnt", "liquid iv", "liquidiv", "nuun"),
    "caffeine": ("coffee", "tea", "soda", "espresso", "energy drink", "latte"),
    "food": ("breakfast", "lunch", "dinner", "snack"),
    "rescue_meds": ("triptan", "sumatriptan", "rizatriptan", "ubrelvy", "nurtec", "ibuprofen",
                    "advil", "tylenol", "excedrin", "meclizine", "zofran"),
    "misc": (),
}
LOOKUP = {a: c for c, al in _GENERIC.items() for a in al}
LOOKUP.update({a: c for c, al in _LABELLED.items() for a in al})
_KEEP_LABEL = {a for al in _LABELLED.values() for a in al}
_MEALS = set(_LABELLED["food"])

DEFAULT_CODES = {
    "w": "water: {n}oz",
    "e": "electrolytes: {n} serving(s)",
    "c": "caffeine: {n} cup(s)",
    "m": "symptoms: migraine {n}/10",
    "d": "symptoms: dizzy {n}/10",
    "v": "symptoms: vertigo {n}/10",
    "n": "symptoms: nausea {n}/10",
    "s": "sinus: sinus pain {n}/10",
    "r": "rescue meds: {text}",
}

COMMANDS = [("rough day", "rough"), ("rough", "rough"), ("pause today", "pause"),
            ("pause", "pause"), ("no reminders", "pause"), ("resume", "resume"),
            ("weekly summary", "summary"), ("summary", "summary")]

_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_LINE_RE = re.compile(r"^[\s>]*([A-Za-z][A-Za-z0-9 ]{0,20}?)\s*:\s*(.*)$")
_SEVERITY_RE = re.compile(r"\b(10|[0-9])\s*/\s*10\b")
_PLACEHOLDER_RE = re.compile(r"^[\s_.\-]*$")
_AT_RE = re.compile(r"(?:^|\s)@\s*([^@]+?)\s*$")
_CLOCK_RE = re.compile(r"^(\d{1,2})(?::?(\d{2}))?(am|pm|a|p)?$")
_CODE_RE = re.compile(r"([a-z]+)(\d+(?:\.\d+)?)?", re.IGNORECASE)
_WORD_TIMES = {"noon": (12, 0), "midnight": (0, 0), "morning": (9, 0), "lunch": (12, 0),
               "afternoon": (15, 0), "evening": (19, 0), "night": (22, 0), "tonight": (22, 0)}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class Entry(NamedTuple):
    category: str
    value: str
    at: Optional[dt.datetime] = None   # set when backdated with @time


class Parsed(NamedTuple):
    entries: list
    command: Optional[str] = None


def normalize_subject(subject):
    return _PREFIX_RE.sub("", subject or "").strip()


def category_for(word):
    word = " ".join(word.strip().lower().rstrip(":").replace("_", " ").split())
    return LOOKUP.get(word) or (word.replace(" ", "_") if word.replace(" ", "_") in CATEGORIES else None)


def _labelled(word, value):
    word = " ".join(word.strip().lower().rstrip(":").split())
    if word not in _KEEP_LABEL:
        return value
    if not value:
        return word
    return f"{word}: {value}" if word in _MEALS else f"{word} {value}"


def severity_of(value):
    """Pull a 0-10 severity out of text like 'headache 6/10'."""
    m = _SEVERITY_RE.search(value)
    return int(m.group(1)) if m else None


# ---- backdating -----------------------------------------------------------

def _clock(text, day_given):
    """Return a list of candidate (hour, minute) for text like '4pm', '14:30', '4'."""
    if text in _WORD_TIMES:
        return [_WORD_TIMES[text]]
    m = _CLOCK_RE.match(text)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")[:1]
    if h > 23 or mi > 59 or (ap and not 1 <= h <= 12):
        return None
    if ap:
        return [(h % 12 + (12 if ap == "p" else 0), mi)]
    if h >= 12 or h == 0:
        return [(h, mi)]
    if day_given:  # "yesterday 4" most likely means 4pm
        return [(h + 12, mi)] if 1 <= h <= 7 else [(h, mi)]
    return [(h, mi), (h + 12, mi)]


def parse_when(text, ref):
    """Parse '2pm', 'yesterday 4pm', 'mon noon', ... relative to ref. None if unclear."""
    words = text.lower().replace(",", " ").split()
    if not words:
        return None
    day = None
    if words[0] in ("yesterday", "yday", "yest"):
        day, words = ref.date() - dt.timedelta(days=1), words[1:]
    elif words[0] == "today":
        day, words = ref.date(), words[1:]
    elif words[0] == "last" and len(words) > 1 and words[1] == "night":
        return dt.datetime.combine(ref.date() - dt.timedelta(days=1), dt.time(22, 0))
    else:
        for i, name in enumerate(_WEEKDAYS):
            if words[0] == name or (len(words[0]) >= 3 and name.startswith(words[0])):
                back = (ref.weekday() - i) % 7
                day, words = ref.date() - dt.timedelta(days=back), words[1:]
                break
    if words:
        options = _clock("".join(words), day is not None)
        if not options:
            return None
    elif day is None:
        return None
    else:
        options = [(12, 0)]

    if day is not None:
        return dt.datetime.combine(day, dt.time(*options[0]))
    limit = ref + dt.timedelta(minutes=5)
    best = None
    for h, mi in options:
        cand = dt.datetime.combine(ref.date(), dt.time(h, mi))
        if cand > limit:
            cand -= dt.timedelta(days=1)
        best = cand if best is None or cand > best else best
    return best


def split_time(text, ref):
    """'16oz @2pm' -> ('16oz', datetime). Unparseable @ text is left alone."""
    m = _AT_RE.search(text)
    if m and ref is not None:
        when = parse_when(m.group(1), ref)
        if when:
            return text[:m.start()].strip(), when
    return text, None


# ---- short codes ----------------------------------------------------------

def _num(n):
    return n[:-2] if n.endswith(".0") else n


def parse_codes(line, codes):
    """'w16 m7' -> [('water','16oz'), ('symptoms','migraine 7/10')], or None."""
    tokens = line.split()
    out = []
    i = 0
    while i < len(tokens):
        m = _CODE_RE.fullmatch(tokens[i])
        code = m.group(1).lower() if m else None
        if code not in codes:
            return None
        cat_word, _, tmpl = codes[code].partition(":")
        cat, tmpl, n = category_for(cat_word), tmpl.strip(), m.group(2)
        if not cat:
            return None
        if "{text}" in tmpl:
            text = " ".join(([n] if n else []) + tokens[i + 1:]) or "taken"
            out.append((cat, tmpl.replace("{text}", text).replace("{n}", n or "")))
            break
        if n is None:
            return None
        out.append((cat, tmpl.replace("{n}", _num(n))))
        i += 1
    return out or None


# ---- messages -------------------------------------------------------------

def _body_lines(body):
    for line in (body or "").splitlines():
        if line.strip() == "--":  # signature delimiter
            break
        yield line


def _clean(value):
    value = value.strip()
    return "" if _PLACEHOLDER_RE.match(value) else value


def _command(subject):
    s = subject.lower().strip(" .!")
    for phrase, cmd in COMMANDS:
        if s == phrase or s.startswith(phrase + " "):
            return cmd
    return None


def _one_off_category(subject):
    """Match 1-2 leading words of the subject to a category."""
    words = subject.split()
    for n in (2, 1):
        if len(words) >= n:
            head = " ".join(words[:n])
            tail = ""
            if n == 1 and ":" in head:  # "Water:16oz"
                head, _, tail = head.partition(":")
            cat = category_for(head)
            if cat:
                return cat, head, (tail + " " + " ".join(words[n:])).strip()
    return None


def parse_message(subject, body, sent_at=None, codes=None):
    """Return Parsed(entries=[Entry...], command)."""
    codes = DEFAULT_CODES if codes is None else codes
    subject, default_at = split_time(normalize_subject(subject), sent_at)
    entries = []

    def add(cat, value, at):
        e = Entry(cat, value, at or default_at)
        if value and e not in entries:
            entries.append(e)

    cmd = _command(subject)
    if cmd:
        return Parsed([], cmd)

    full_log = re.search(r"check[\s-]?in|^log\b", subject, re.IGNORECASE)
    if not full_log:
        coded = parse_codes(subject, codes) if subject else None
        if coded:
            for cat, value in coded:
                add(cat, value, None)
            return Parsed(entries)
        one_off = _one_off_category(subject)
        if one_off:
            cat, word, value = one_off
            value = _clean(value)
            if not value:
                for line in _body_lines(body):
                    stripped = line.strip()
                    if stripped.startswith(">"):
                        break
                    if _clean(stripped):
                        value = _clean(stripped)
                        break
            value, at = split_time(value, sent_at)
            add(cat, _labelled(word, value), at)
            return Parsed(entries)

    for line in _body_lines(body):
        m = _LINE_RE.match(line)
        cat = category_for(m.group(1)) if m else None
        if cat:
            value, at = split_time(_clean(m.group(2)), sent_at)
            if _clean(value):
                add(cat, _labelled(m.group(1), _clean(value)), at)
            continue
        if line.lstrip().startswith(">"):
            continue  # codes only count in your own text, not quoted mail
        text, at = split_time(line.strip(), sent_at)
        for cat, value in parse_codes(text, codes) or []:
            add(cat, value, at)
    return Parsed(entries)


def html_to_text(markup):
    markup = re.sub(r"(?is)<(script|style).*?</\1>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", markup)
    markup = re.sub(r"<[^>]+>", "", markup)
    return html.unescape(markup).replace("\xa0", " ")


def message_text(msg):
    """Best-effort plain text body of an email.message.EmailMessage."""
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        return part.get_content()
    part = msg.get_body(preferencelist=("html",))
    if part is not None:
        return html_to_text(part.get_content())
    return ""
