import datetime as dt
import tempfile
import unittest
from pathlib import Path

from symptom_tracker import config, mailer, parser, report, service, weather
from symptom_tracker.store import Store, servings, water_ounces

NOW = dt.datetime(2026, 9, 30, 15, 0)  # a Wednesday afternoon


def p(subject, body="", sent_at=NOW):
    """Entries without their times."""
    return [(e.category, e.value) for e in parser.parse_message(subject, body, sent_at).entries]


def times(subject, body="", sent_at=NOW):
    return [e.at for e in parser.parse_message(subject, body, sent_at).entries]


class OneOffTests(unittest.TestCase):
    def test_subject_only(self):
        self.assertEqual(p("WATER 16oz"), [("water", "16oz")])

    def test_subject_with_colon(self):
        self.assertEqual(p("Symptom: headache 6/10"), [("symptoms", "headache 6/10")])
        self.assertEqual(p("food:toast"), [("food", "toast")])

    def test_value_in_body(self):
        body = "turkey sandwich and chips\n\nSent from my iPhone"
        self.assertEqual(p("FOOD", body), [("food", "turkey sandwich and chips")])

    def test_meal_label_kept(self):
        self.assertEqual(p("lunch salad"), [("food", "lunch: salad")])

    def test_empty_one_off(self):
        self.assertEqual(p("WATER", "> quoted only"), [])

    def test_named_symptom_and_new_categories(self):
        self.assertEqual(p("MIGRAINE 6/10"), [("symptoms", "migraine 6/10")])
        self.assertEqual(p("SINUS PAIN 5/10"), [("sinus", "5/10")])
        self.assertEqual(p("Sinus 4/10"), [("sinus", "4/10")])
        self.assertEqual(p("COFFEE"), [("caffeine", "coffee")])
        self.assertEqual(p("caffeine 2 cups"), [("caffeine", "2 cups")])
        self.assertEqual(p("ELECTROLYTES 1 serving"), [("electrolytes", "1 serving")])
        self.assertEqual(p("LMNT"), [("electrolytes", "lmnt")])
        self.assertEqual(p("RESCUE sumatriptan 50mg"), [("rescue_meds", "sumatriptan 50mg")])
        self.assertEqual(p("sumatriptan"), [("rescue_meds", "sumatriptan")])

    def test_nap_and_left_early(self):
        self.assertEqual(p("NAP 30 min"), [("nap", "30 min")])
        self.assertEqual(p("NAP"), [("nap", "nap")])
        self.assertEqual(p("napped 1 hr"), [("nap", "1 hr")])
        self.assertEqual(p("LEFT EARLY"), [("left_early", "left early")])
        self.assertEqual(p("LEFT EARLY migraine"), [("left_early", "migraine")])
        self.assertEqual(p("went home early dizzy"), [("left_early", "dizzy")])
        self.assertEqual(times("NAP @yesterday"), [dt.datetime(2026, 9, 29, 12, 0)])
        self.assertEqual(times("left work early @1pm"), [NOW.replace(hour=13)])


class FullLogTests(unittest.TestCase):
    def test_full_log(self):
        body = ("Symptoms: headache 6/10\nSinus pain: 3/10\nWater: 16oz\nElectrolytes: 1\n"
                "Caffeine: 1 coffee\nFood: toast\nRescue meds: rizatriptan\nMisc: slept badly\n")
        self.assertEqual(p("LOG", body), [
            ("symptoms", "headache 6/10"), ("sinus", "3/10"), ("water", "16oz"),
            ("electrolytes", "1"), ("caffeine", "1 coffee"), ("food", "toast"),
            ("rescue_meds", "rizatriptan"), ("misc", "slept badly")])

    def test_blanks_skipped(self):
        self.assertEqual(p("LOG", mailer.TEMPLATE), [])
        self.assertEqual(p("LOG", "Symptoms: ___\nWater: 8oz\nFood:\nMisc: -\n"), [("water", "8oz")])

    def test_reply_to_reminder(self):
        subject, text, _ = mailer.reminder(config.DEFAULTS | {"tracker_email": "t@gmail.com"}, NOW)
        quoted = "\n".join("> " + l for l in text.splitlines())
        body = ("Symptoms: nausea 3/10\nWater: 24 oz\n\n"
                "On Wed, Sep 30, 2026 at 3:00 PM <t@gmail.com> wrote:\n" + quoted)
        self.assertEqual(p("Re: " + subject, body), [("symptoms", "nausea 3/10"), ("water", "24 oz")])

    def test_inline_quoted_answers(self):
        body = "> Symptoms: dizzy\n> Water: \n> Food: crackers\n"
        self.assertEqual(p("RE: Symptom check-in", body), [("symptoms", "dizzy"), ("food", "crackers")])

    def test_signature_ignored(self):
        self.assertEqual(p("log", "Water: 8oz\n--\nMisc: my signature\n"), [("water", "8oz")])

    def test_html_body(self):
        text = parser.html_to_text("<div>Symptoms: cramps&nbsp;4/10<br>Water: 1 cup</div>")
        self.assertEqual(p("LOG", text), [("symptoms", "cramps 4/10"), ("water", "1 cup")])


class BackdateTests(unittest.TestCase):
    def test_clock_times(self):
        self.assertEqual(times("WATER 16oz @2pm"), [NOW.replace(hour=14)])
        self.assertEqual(times("WATER 16oz @ 2:30 pm"), [NOW.replace(hour=14, minute=30)])
        self.assertEqual(times("WATER 16oz @14:30"), [NOW.replace(hour=14, minute=30)])
        self.assertEqual(p("WATER 16oz @2pm"), [("water", "16oz")])

    def test_bare_hour_picks_most_recent(self):
        self.assertEqual(times("WATER 16oz @2"), [NOW.replace(hour=14)])     # 2pm, not 2am
        self.assertEqual(times("WATER 16oz @4"), [NOW.replace(hour=4)])      # 4pm is in the future

    def test_future_time_means_yesterday(self):
        self.assertEqual(times("WATER 8oz @9pm"), [dt.datetime(2026, 9, 29, 21, 0)])

    def test_days(self):
        self.assertEqual(times("m6 @yesterday 4pm"), [dt.datetime(2026, 9, 29, 16, 0)])
        self.assertEqual(times("m6 @yesterday 4"), [dt.datetime(2026, 9, 29, 16, 0)])
        self.assertEqual(times("m6 @mon noon"), [dt.datetime(2026, 9, 28, 12, 0)])
        self.assertEqual(times("m6 @last night"), [dt.datetime(2026, 9, 29, 22, 0)])
        self.assertEqual(times("m6 @yesterday"), [dt.datetime(2026, 9, 29, 12, 0)])

    def test_whole_email(self):
        at = NOW.replace(hour=12)
        self.assertEqual(times("LOG @noon", "Water: 8oz\nFood: toast @11am\n"),
                         [at, NOW.replace(hour=11)])

    def test_email_addresses_left_alone(self):
        self.assertEqual(p("MISC emailed bob@x.com"), [("misc", "emailed bob@x.com")])
        self.assertEqual(times("MISC note @someday"), [None])


class ShortCodeTests(unittest.TestCase):
    def test_subject_codes(self):
        self.assertEqual(p("w16 m7"), [("water", "16oz"), ("symptoms", "migraine 7/10")])
        self.assertEqual(p("W16"), [("water", "16oz")])
        self.assertEqual(p("s4 e1 c2"), [("sinus", "sinus pain 4/10"),
                                         ("electrolytes", "1 serving(s)"), ("caffeine", "2 cup(s)")])
        self.assertEqual(p("r sumatriptan 50mg"), [("rescue_meds", "sumatriptan 50mg")])
        self.assertEqual(p("r"), [("rescue_meds", "rescue meds")])
        self.assertEqual(p("z45"), [("nap", "45 min")])
        self.assertEqual(p("le migraine"), [("left_early", "migraine")])
        self.assertEqual(p("le"), [("left_early", "left early")])

    def test_codes_with_time(self):
        self.assertEqual(times("w16 d5 @1pm"), [NOW.replace(hour=13)] * 2)

    def test_codes_in_body(self):
        self.assertEqual(p("LOG", "w8\nd4 @noon\nFood: soup\n"),
                         [("water", "8oz"), ("symptoms", "dizzy 4/10"), ("food", "soup")])

    def test_not_codes(self):
        self.assertEqual(p("Hello there"), [])
        self.assertEqual(p("LOG", "> w16\nw16 = water\n"), [])  # quoted / not all codes

    def test_custom_codes(self):
        codes = config.codes_from_text("h = symptoms: headache {n}/10\nsalt = electrolytes: {n}g salt")
        entries = parser.parse_message("h3 salt1", "", NOW, codes).entries
        self.assertEqual([(e.category, e.value) for e in entries],
                         [("symptoms", "headache 3/10"), ("electrolytes", "1g salt")])
        with self.assertRaises(ValueError):
            config.codes_from_text("x = nonsense: {n}")


class CommandTests(unittest.TestCase):
    def test_commands(self):
        for subject, cmd in [("ROUGH DAY", "rough"), ("rough", "rough"), ("Pause", "pause"),
                             ("RESUME", "resume"), ("summary", "summary")]:
            self.assertEqual(parser.parse_message(subject, "", NOW).command, cmd)
        self.assertIsNone(parser.parse_message("WATER 8oz", "", NOW).command)


class HelperTests(unittest.TestCase):
    def test_severity(self):
        self.assertEqual(parser.severity_of("headache 6/10"), 6)
        self.assertEqual(parser.severity_of("pain 10 / 10"), 10)
        self.assertIsNone(parser.severity_of("headache"))

    def test_amounts(self):
        self.assertEqual(water_ounces("16oz"), 16)
        self.assertEqual(water_ounces("2 cups"), 16)
        self.assertAlmostEqual(water_ounces("500 ml"), 16.9, places=1)
        self.assertEqual(servings("2 cup(s)"), 2)
        self.assertEqual(servings("coffee"), 1)

    def test_pollen_summary(self):
        text = ("Good morning!\nToday's pollen forecast for your area\nTree pollen: High\n"
                "Grass: Low\nWeed: Moderate\nUnsubscribe here")
        self.assertEqual(weather.pollen_summary("Pollen alert", text),
                         "Tree pollen: High; Grass: Low; Weed: Moderate")
        self.assertEqual(weather.pollen_summary("Pollen alert", "nothing useful"), "Pollen alert")


class ScheduleTests(unittest.TestCase):
    cfg = {"reminder_days": ["Mon"], "reminder_times": ["10:00", "13:00"],
           "summary_enabled": True, "summary_day": "Sun", "summary_time": "18:00"}

    def test_reminders(self):
        monday = dt.datetime(2026, 9, 28, 13, 10)
        due = service.due_reminder
        self.assertEqual(due(self.cfg, monday, lambda s: False), dt.datetime(2026, 9, 28, 13, 0))
        self.assertIsNone(due(self.cfg, monday, lambda s: True))
        self.assertIsNone(due(self.cfg, monday.replace(hour=14), lambda s: False))
        self.assertIsNone(due(self.cfg, monday + dt.timedelta(days=1), lambda s: False))
        self.assertEqual(service.next_reminder(self.cfg, monday), dt.datetime(2026, 10, 5, 10, 0))

    def test_rough_and_pause(self):
        morning = dt.datetime(2026, 9, 28, 10, 5)
        self.assertIsNone(service.due_reminder(self.cfg, morning, lambda s: False, "rough"))
        self.assertIsNotNone(service.due_reminder(self.cfg, morning.replace(hour=13), lambda s: False, "rough"))
        self.assertIsNone(service.due_reminder(self.cfg, morning, lambda s: False, "pause"))

    def test_summary(self):
        sunday = dt.datetime(2026, 10, 4, 18, 30)
        self.assertEqual(service.due_summary(self.cfg, sunday, lambda s: False),
                         dt.datetime(2026, 10, 4, 18, 0))
        self.assertIsNotNone(service.due_summary(self.cfg, sunday + dt.timedelta(hours=12), lambda s: False))
        self.assertIsNone(service.due_summary(self.cfg, sunday + dt.timedelta(days=2), lambda s: False))
        self.assertIsNone(service.due_summary(self.cfg, sunday, lambda s: True))


class StoreAndReportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_roundtrip(self):
        s = self.store
        s.add_entries([("water", "16oz"), ("symptoms", "headache 5/10"),
                       ("water", "8oz", dt.datetime(2020, 1, 1))], message_id="<a@b>")
        self.assertTrue(s.is_processed("<a@b>"))
        self.assertEqual(s.water_today(), 16)
        self.assertEqual(len(s.recent()), 3)
        self.assertEqual(s.export_csv(Path(self.dir.name) / "out.csv"), 3)
        s.set_day_mode("rough")
        self.assertEqual(s.day_mode(), "rough")
        s.set_day_mode("normal")
        self.assertEqual(s.day_mode(), "normal")

    def test_reports(self):
        s = self.store
        today = dt.date.today()
        for i in range(20):
            day = dt.datetime.combine(today - dt.timedelta(days=i), dt.time(12))
            entries = [("water", f"{20 + i * 3}oz", day)]
            if i % 3 == 0:
                entries += [("symptoms", f"migraine {i % 10}/10", day), ("rescue_meds", "sumatriptan", day)]
            if i % 4 == 0:
                entries.append(("symptoms", "dizzy 4/10", day))
            if i == 1:
                entries += [("left_early", "migraine", day), ("nap", "1 hr", day)]
            s.add_entries(entries)
        s.save_weather([{"day": str(today - dt.timedelta(days=i)), "temp_max": 80, "temp_min": 60,
                         "humidity": 50, "pressure_mean": 1015 - (8 if i == 3 else 0),
                         "pressure_min": 1010, "pressure_max": 1020, "precip": 0} for i in range(21)])
        s.save_pollen(today, "Tree pollen: High", "raw")
        cfg = dict(config.DEFAULTS)
        subject, text, html = report.weekly_summary(cfg, s)
        self.assertIn("Migraine/headache days: 3", text)
        self.assertIn("Big pressure drops", text)
        self.assertIn("High pollen", text)
        self.assertIn("Naps: 1 days   Left work early: 1 days", text)
        page = report.doctor_report(cfg, s, today - dt.timedelta(days=29), today)
        self.assertIn("<svg", page)
        self.assertIn("sumatriptan", page)
        self.assertIn("left early: migraine", page)
        self.assertEqual(s.rescue_days(today.year, today.month),
                         len({(today - dt.timedelta(days=i)) for i in range(0, 20, 3)
                              if (today - dt.timedelta(days=i)).month == today.month}))

    def test_reminder_email(self):
        cfg = dict(config.DEFAULTS, tracker_email="t@gmail.com")
        self.store.add_entries([("water", "16oz")])
        subject, text, html = mailer.reminder(cfg, NOW, self.store)
        self.assertIn("Water so far today: 16 of 64 oz", text)
        self.assertIn("w16 = water 16oz", text)
        self.assertIn("m6 = migraine 6/10", text)
        self.assertIn("r sumatriptan = rescue meds sumatriptan", text)
        self.assertIn("ROUGH%20DAY", html)
        _, rough_text, rough_html = mailer.reminder(cfg, NOW, self.store, rough=True)
        self.assertIn("only check-in today", rough_text)
        self.assertIn("RESUME", rough_html)
        _, _, first_html = mailer.reminder(cfg, NOW, self.store, first=True)
        self.assertIn("NAP%20%40yesterday", first_html)
        self.assertNotIn("NAP%20%40yesterday", html)
        self.assertIn("le migraine = left early migraine", text)
        self.assertIn("z30 = nap 30 min", text)


if __name__ == "__main__":
    unittest.main()
