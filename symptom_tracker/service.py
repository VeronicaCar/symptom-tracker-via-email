"""Background worker: checks the inbox, sends reminders and the weekly
summary on schedule, and keeps daily weather up to date."""

import datetime as dt
import logging
import queue
import threading

from . import config, creds, mailer, report
from . import weather as wx

log = logging.getLogger(__name__)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
REMINDER_GRACE = dt.timedelta(minutes=30)   # skip reminders the app was too late for
SUMMARY_GRACE = dt.timedelta(hours=24)      # a late weekly summary is still useful
WEATHER_EVERY = dt.timedelta(hours=3)
RETRY_AFTER = dt.timedelta(minutes=5)


def _slots(cfg, day):
    out = []
    for hhmm in sorted(cfg["reminder_times"]):
        h, m = (int(x) for x in hhmm.split(":"))
        out.append(dt.datetime.combine(day, dt.time(h, m)))
    return out


def todays_slots(cfg, day, mode="normal"):
    """Reminder times for a day, after the rough-day/pause setting."""
    if DAYS[day.weekday()] not in cfg["reminder_days"] or mode == "pause":
        return []
    slots = _slots(cfg, day)
    return slots[-1:] if mode == "rough" else slots


def due_reminder(cfg, now, already_sent, mode="normal"):
    """Return the slot datetime of a reminder that should go out now, if any."""
    for slot in todays_slots(cfg, now.date(), mode):
        if slot <= now < slot + REMINDER_GRACE and not already_sent(slot.strftime("%Y-%m-%d %H:%M")):
            return slot
    return None


def next_reminder(cfg, now, mode_for=lambda day: "normal"):
    for offset in range(8):
        day = (now + dt.timedelta(days=offset)).date()
        for slot in todays_slots(cfg, day, mode_for(day)):
            if slot > now:
                return slot
    return None


def due_summary(cfg, now, already_sent):
    """Date of the week-end the summary covers (the day before), if one is due."""
    if not cfg.get("summary_enabled"):
        return None
    h, m = (int(x) for x in cfg["summary_time"].split(":"))
    target = DAYS.index(cfg["summary_day"])
    back = (now.weekday() - target) % 7
    slot = dt.datetime.combine(now.date() - dt.timedelta(days=back), dt.time(h, m))
    if slot <= now < slot + SUMMARY_GRACE and not already_sent(f"summary {slot.date()}"):
        return slot
    return None


class Worker(threading.Thread):
    def __init__(self, store, events):
        super().__init__(daemon=True)
        self.store = store
        self.events = events          # queue the GUI reads: (kind, data)
        self.requests = queue.Queue()  # "check", "remind", "summary", "weather", "reload"
        self.stop_flag = threading.Event()
        self.cfg = config.load()
        self.last_check = None
        self._failed = {}             # job -> time of last failure, to avoid hammering

    def _password(self):
        pw = creds.get_password(self.cfg["tracker_email"])
        if not pw:
            raise RuntimeError("No app password saved. Open Settings to add it.")
        return pw

    # ---- jobs ------------------------------------------------------------

    def check_inbox(self):
        results = mailer.fetch_logs(self.cfg, self._password(), self.store)
        self.last_check = dt.datetime.now()
        count = sum(len(r["entries"]) for r in results)
        mode = self.cfg["reply_to_logs"]
        recent = dt.datetime.now() - dt.timedelta(days=1)
        for r in results:
            cmd = r["command"]
            if cmd in ("rough", "pause", "resume"):
                self.store.set_day_mode("normal" if cmd == "resume" else cmd, r["when"].date())
                self.events.put(("mode", None))
            if r["when"] < recent:  # old mail picked up on catch-up; don't act or reply
                continue
            if cmd == "summary":
                self.send_summary(to=r["sender"])
            if cmd or mode == "always" or (mode == "errors" and not r["entries"]):
                subject, text = mailer.confirmation(r["entries"], cmd)
                mailer.send(self.cfg, self._password(), r["sender"], subject, text,
                            in_reply_to=r["message_id"])
        self.events.put(("checked", count))

    def send_reminder(self, slot=None):
        slot = slot or dt.datetime.now()
        mode = self.store.day_mode(slot.date())
        slots = todays_slots(self.cfg, slot.date(), mode)
        first = bool(slots) and slot == slots[0]
        subject, text, html = mailer.reminder(self.cfg, slot, self.store,
                                              rough=mode == "rough", first=first)
        mailer.send(self.cfg, self._password(), self.cfg["reminder_to"], subject, text, html)
        self.store.record_reminder(slot.strftime("%Y-%m-%d %H:%M"))
        self.events.put(("reminded", slot))

    def send_summary(self, slot=None, to=None):
        end = slot.date() if slot else None
        subject, text, html = report.weekly_summary(self.cfg, self.store, end)
        mailer.send(self.cfg, self._password(), to or self.cfg["reminder_to"], subject, text, html)
        if slot:
            self.store.record_reminder(f"summary {slot.date()}")
        self.events.put(("summary", None))

    def refresh_weather(self):
        lat, lon = self.cfg.get("weather_lat"), self.cfg.get("weather_lon")
        if lat is None or lon is None:
            return
        yesterday = self.store.weather_fetched_at(dt.date.today() - dt.timedelta(days=1))
        past = 2 if yesterday else 30  # backfill a month the first time
        self.store.save_weather(wx.fetch_daily(lat, lon, past_days=past))
        self.events.put(("weather", None))

    def _weather_due(self, now):
        if self.cfg.get("weather_lat") is None:
            return False
        last = self.store.weather_fetched_at()
        return last is None or now - last >= WEATHER_EVERY

    def _safely(self, fn, *args, job=None, **kw):
        job = job or fn.__name__
        try:
            fn(*args, **kw)
            self._failed.pop(job, None)
        except Exception as e:  # keep running; show the problem in the window
            log.exception("%s failed", job)
            self._failed[job] = dt.datetime.now()
            self.events.put(("error", str(e)))

    def _backing_off(self, job, now):
        failed = self._failed.get(job)
        return failed is not None and now - failed < RETRY_AFTER

    # ---- loop ------------------------------------------------------------

    def run(self):
        next_poll = dt.datetime.now()
        while not self.stop_flag.is_set():
            try:
                req = self.requests.get(timeout=20)
            except queue.Empty:
                req = None
            if req == "reload":
                self.cfg = config.load()
                next_poll = dt.datetime.now()
                self._failed.clear()
            if not config.is_configured(self.cfg):
                continue
            now = dt.datetime.now()
            if req == "check" or (now >= next_poll and not self._backing_off("inbox", now)):
                self._safely(self.check_inbox, job="inbox")
                next_poll = now + dt.timedelta(minutes=self.cfg["poll_minutes"])
            if req == "remind":
                self._safely(self.send_reminder, job="manual reminder")
            if req == "summary":
                self._safely(self.send_summary, job="manual summary")
            if req in ("weather", "reload") or (self._weather_due(now)
                                                and not self._backing_off("weather", now)):
                self._safely(self.refresh_weather, job="weather")

            mode = self.store.day_mode(now.date())
            slot = due_reminder(self.cfg, now, self.store.reminder_sent, mode)
            if slot and not self._backing_off("reminder", now):
                skip = self.cfg.get("skip_if_logged_minutes", 0)
                last = self.store.last_created()
                if skip and last and now - last < dt.timedelta(minutes=skip):
                    self.store.record_reminder(slot.strftime("%Y-%m-%d %H:%M"))
                    self.events.put(("skipped", slot))
                else:
                    self._safely(self.send_reminder, slot, job="reminder")
            summary_slot = due_summary(self.cfg, now, self.store.reminder_sent)
            if summary_slot and not self._backing_off("summary", now):
                self._safely(self.send_summary, summary_slot, job="summary")

    def stop(self):
        self.stop_flag.set()
        self.requests.put(None)
