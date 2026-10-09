"""Reading log emails over IMAP and sending mail over SMTP."""

import datetime as dt
import email
import imaplib
import re
import smtplib
import ssl
import urllib.parse
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

from . import parser
from . import weather as wx

TEMPLATE = ("Symptoms: \nSinus pain: \nWater: \nElectrolytes: \nCaffeine: \nFood: \n"
            "Rescue meds: \nMisc: \n")


def _local_time(msg):
    try:
        return parsedate_to_datetime(msg["Date"]).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return dt.datetime.now()


def _spoofed(msg):
    """Gmail stamps a DMARC verdict on incoming mail; trust it when it fails."""
    results = " ".join(msg.get_all("Authentication-Results", [])).lower()
    return "dmarc=fail" in results


LOOKBACK_DAYS = 30


def _fetch_one(imap, uid, spec):
    _, parts = imap.uid("FETCH", uid, f"({spec})")
    return next((p[1] for p in parts if isinstance(p, tuple)), None)


def _matches(sender, patterns):
    """Exact address, or a bare domain like 'pollen.com' / '@pollen.com'."""
    domain = sender.rpartition("@")[2]
    return any(sender == p or domain == p.lstrip("@") for p in patterns)


def fetch_logs(cfg, password, store):
    """Log every email from an allowed sender in the last LOOKBACK_DAYS that
    hasn't been logged yet, read or not. Entries are timestamped with when the
    email was sent (or the @time written in it), so anything that arrived while
    the PC was off lands at the right time once the app starts. Emails from
    pollen senders are saved as that day's pollen report.

    Returns a list of dicts: {sender, subject, entries, command, when,
    message_id}. Mail from other senders is left untouched.
    """
    results = []
    allowed = set(cfg["allowed_senders"])
    pollen_from = [p.lower() for p in cfg.get("pollen_senders", [])]
    codes = cfg.get("short_codes") or parser.DEFAULT_CODES
    since = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(cfg["imap_host"], ssl_context=ssl.create_default_context()) as imap:
        imap.login(cfg["tracker_email"], password)
        imap.select("INBOX")
        _, data = imap.uid("SEARCH", None, "SINCE", since)
        uids = data[0].split()
        if not uids:
            return results
        # Headers for everything in one round trip, so already-logged mail
        # isn't downloaded again.
        _, parts = imap.uid("FETCH", b",".join(uids),
                            "(UID BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])")
        headers = {}
        for p in parts:
            if isinstance(p, tuple):
                m = re.search(rb"UID (\d+)", p[0])
                if m:
                    headers[m.group(1)] = p[1]
        for uid in uids:
            head = headers.get(uid)
            if head is None:
                continue
            hdr = email.message_from_bytes(head, policy=policy.default)
            sender = parseaddr(hdr.get("From", ""))[1].lower()
            message_id = hdr.get("Message-ID") or f"uid-{uid.decode()}"
            is_pollen = bool(pollen_from) and _matches(sender, pollen_from)
            if (sender not in allowed and not is_pollen) or store.is_processed(message_id):
                continue
            raw = _fetch_one(imap, uid, "BODY.PEEK[]")
            if raw is None:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            if _spoofed(msg):
                continue
            when = _local_time(msg)
            subject = msg.get("Subject", "")
            body = parser.message_text(msg)
            if is_pollen:
                store.save_pollen(when.date(), wx.pollen_summary(subject, body), body[:5000])
                store.mark_processed(message_id)
                imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                continue
            parsed = parser.parse_message(subject, body, sent_at=when, codes=codes)
            if parsed.entries:
                store.add_entries(parsed.entries, when=when, message_id=message_id)
            else:
                store.mark_processed(message_id)
            results.append({"sender": sender, "subject": subject, "entries": parsed.entries,
                            "command": parsed.command, "when": when,
                            "message_id": msg.get("Message-ID")})
            imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    return results


def send(cfg, password, to, subject, text, html=None, in_reply_to=None):
    msg = EmailMessage()
    msg["From"] = cfg["tracker_email"]
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"],
                          context=ssl.create_default_context()) as smtp:
        smtp.login(cfg["tracker_email"], password)
        smtp.send_message(msg)


def test_login(cfg, password):
    """Log in to IMAP and SMTP without reading or sending anything."""
    with imaplib.IMAP4_SSL(cfg["imap_host"], ssl_context=ssl.create_default_context()) as imap:
        imap.login(cfg["tracker_email"], password)
    with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"],
                          context=ssl.create_default_context()) as smtp:
        smtp.login(cfg["tracker_email"], password)


def _mailto(to, subject, body=""):
    q = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{to}?{q}"


def _button(href, label, primary=False):
    bg, fg = ("#2f6f5e", "#ffffff") if primary else ("#e8f0ed", "#1f4a3f")
    return (f'<a href="{href}" style="display:inline-block;margin:4px 6px 4px 0;'
            f'padding:10px 14px;border-radius:8px;background:{bg};color:{fg};'
            f'text-decoration:none;font-weight:600">{label}</a>')


def code_examples(codes):
    """'w16 = water 16oz · m7 = migraine 7/10 · ...' for the reminder footer."""
    out = []
    for code, spec in codes.items():
        cat_word, _, tmpl = spec.partition(":")
        tmpl = tmpl.strip()
        label = parser.LABELS.get(parser.category_for(cat_word) or "", cat_word).lower()
        if "{text}" in tmpl:
            word = {"rescue meds": "sumatriptan", "left early": "2 migraine"}.get(label, "…")
            cat = parser.category_for(cat_word)
            example = f"{code}{word}" if cat == "left_early" else f"{code} {word}"
            code, value = example, parser.normalize(cat, tmpl.replace("{text}", word))
            if parser.hours_early(value) is not None:
                value = f"left {value}"
        else:
            n = "16" if "oz" in tmpl else "30" if "min" in tmpl else "1" if "{n} " in tmpl else "6"
            code, value = f"{code}{n}", tmpl.replace("{n}", n)
        if label != "symptoms" and label.split()[0] not in value.lower():
            value = f"{label} {value}"
        out.append(f"{code} = {value}")
    return out


def _water_line(cfg, store, now):
    goal = cfg.get("water_goal_oz", 64)
    oz = store.day_totals(now.date())["water"]
    # Rough pace: the goal spread evenly from 8am to 8pm.
    pace = goal * min(max((now.hour + now.minute / 60 - 8) / 12, 0), 1)
    line = f"Water so far today: {oz:.0f} of {goal} oz."
    if oz >= goal:
        line += " Goal reached!"
    elif oz < pace * 0.75:
        line += " A little behind, a glass now would help."
    return line, min(oz / goal, 1) if goal else 0


def reminder(cfg, when, store=None, rough=False, first=False):
    """Build (subject, text, html) for a check-in reminder."""
    to = cfg["tracker_email"]
    label = when.strftime("%I:%M %p").lstrip("0")
    subject = f"Symptom check-in ({label})"
    codes = cfg.get("short_codes") or parser.DEFAULT_CODES
    notes = []
    progress = None
    if store is not None:
        water, progress = _water_line(cfg, store, dt.datetime.now())
        notes.append(water)
        n = store.rescue_days(when.year, when.month)
        if n >= 8:
            notes.append(f"Heads up: rescue meds on {n} days this month. "
                         "10+ days a month can cause rebound headaches.")
    intro = ("Rough day, so this is the only check-in today. Log just what you can."
             if rough else "Time to check in.")
    examples = code_examples(codes)
    text = (
        f"{intro}\n" + "".join(f"{n}\n" for n in notes) +
        "\nReply to this email and fill in whatever applies. Leave anything blank to skip it.\n\n"
        f"{TEMPLATE}\n"
        f"Quick one-off: email {to} with a subject like \"WATER 16oz\", \"MIGRAINE 6/10\" or a short code.\n"
        "Short codes: " + " · ".join(examples) + "\n"
        "Add @time to backdate, e.g. \"w16 @2pm\" or \"m6 @yesterday 4pm\".\n"
        "Subject ROUGH DAY = only one check-in today, PAUSE = none today, RESUME = back to normal.\n"
    )
    quick = [
        ("+ 8oz water", "WATER 8oz"), ("+ 16oz water", "WATER 16oz"),
        ("Electrolytes", "ELECTROLYTES 1 serving"), ("Caffeine", "CAFFEINE "),
        ("Migraine", "MIGRAINE /10"), ("Dizzy", "DIZZY /10"), ("Sinus pain", "SINUS /10"),
        ("Rescue med", "RESCUE "), ("Advil", "ADVIL 2"), ("Food", "FOOD "), ("Nap", "NAP "),
        ("Leaving early", "LEFT EARLY 2h "), ("Note", "MISC "),
    ]
    bar = ""
    if progress is not None:
        bar = ("<div style='background:#e3ecef;border-radius:6px;height:10px;width:260px;margin:4px 0 10px'>"
               f"<div style='background:#2e86c1;border-radius:6px;height:10px;width:{progress * 100:.0f}%'>"
               "</div></div>")
    yesterday = [("Napped yesterday", "NAP @yesterday"),
                 ("Left early yesterday", "LEFT EARLY 2h @yesterday")] if first else []
    day_buttons = [("Resume normal", "RESUME")] if rough else [
        ("Rough day (1 check-in)", "ROUGH DAY"), ("Pause today", "PAUSE")]
    html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#1c1c1c">'
        f"<p style='margin-bottom:6px'><b>{intro}</b></p>"
        + "".join(f"<p style='margin:2px 0'>{n}</p>" for n in notes) + bar +
        "<p>Tap below to open a fill-in-the-blanks log, or just reply to this email.</p>"
        f"<p>{_button(_mailto(to, 'LOG', TEMPLATE), 'Fill in a full log', primary=True)}</p>"
        "<p style='margin-bottom:2px;color:#555'>Or add just one thing:</p><p>"
        + "".join(_button(_mailto(to, s), label) for label, s in quick)
        + ("</p><p style='margin-bottom:2px;color:#555'>Anything from yesterday?</p><p>"
           + "".join(_button(_mailto(to, s), label) for label, s in yesterday) if yesterday else "")
        + "</p><p style='margin-bottom:2px;color:#555'>How's today going?</p><p>"
        + "".join(_button(_mailto(to, s), label) for label, s in day_buttons)
        + "</p><p style='color:#555;font-size:13px'>Short codes: "
        + " · ".join(examples) + "<br>Add @time to backdate, e.g. <b>w16 @2pm</b>.</p></div>"
    )
    return subject, text, html


def confirmation(entries, command=None):
    if command:
        msg = {"rough": "Rough day noted. You'll get just one check-in today. Take care of yourself.",
               "pause": "Reminders paused for the rest of today.",
               "resume": "Reminders are back to normal.",
               "summary": "Summary sent."}[command]
        return "Got it", msg + "\n"
    if not entries:
        return ("Couldn't read that log",
                "I couldn't find anything to log in that email.\n\n"
                "For a full log, put one item per line:\n\n" + TEMPLATE +
                "\nFor a single item, put it in the subject, like \"WATER 16oz\" "
                "or \"MIGRAINE 6/10\", or use a short code like \"w16\".\n")
    lines = "\n".join(
        f"  {parser.LABELS.get(e.category, e.category)}: {e.value}"
        + (f"  (at {e.at.strftime('%a %I:%M %p')})" if e.at else "")
        for e in entries)
    return "Logged", f"Logged {len(entries)} item(s):\n\n{lines}\n"
