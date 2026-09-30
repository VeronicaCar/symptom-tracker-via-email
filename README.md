# Symptom Tracker

A small Windows app that logs symptoms, sinus pain, water, electrolytes, caffeine,
food, rescue meds, naps, leaving work early, blood pressure, heart rate, O2
and notes that you
email to a dedicated Gmail address, and emails you fill-in-the-blanks check-in
reminders during the work day. Everything is stored locally in
`symptom_log.db`. It only uses Python's standard library, so nothing to install.

## One-time setup

1. Create a new Gmail account just for this (e.g. `yourname.symptoms@gmail.com`).
2. In that account, turn on 2-Step Verification:
   Google Account → Security → 2-Step Verification.
3. Create an app password at <https://myaccount.google.com/apppasswords>
   (name it "Symptom Tracker"). Google shows a 16-letter code; copy it.
4. Double-click **`Symptom Tracker.pyw`**. The Settings window opens on first run:
   - **Tracker Gmail address**: the new account.
   - **Gmail app password**: the 16-letter code. It's saved in Windows
     Credential Manager, never in a file.
   - **Accept logs from**: the addresses you'll send logs *from* (work email,
     personal email), comma separated. Mail from anyone else is ignored.
   - **Send reminders to**: where you want the check-in emails (probably your work email).
5. Click **Test connection** (it logs in but sends nothing), then **Save**.

The app checks the inbox every 5 minutes while its window is open. Closing the
window stops it; minimize it instead. Tick **Start with Windows** in Settings
to have it open minimized when you log in.

Your PC doesn't need to stay on. Logs wait in Gmail, and when the app starts it
picks up anything from the last 30 days it hasn't logged yet (read or unread),
timestamped with when you sent it. Reminders are the exception: they can only
go out while the app is running.

## Sending logs

Send these to the tracker Gmail address.

**Full log**: subject `LOG` (or reply to a check-in reminder), one item per line.
Leave lines blank to skip them.

```
Symptoms: migraine 6/10, a bit dizzy
Sinus pain: 3/10
Water: 16oz
Electrolytes: 1 LMNT
Caffeine: 1 coffee
Food: turkey sandwich
Rescue meds: sumatriptan 50mg
Misc: slept badly
```

Inside a full log you can also use subject-style lines without a colon, as
long as the category word is in capitals (`LEFT EARLY 3.5h vertigo`) or is
BP, HR or O2 (`BP 113/75 @ 1 pm`).

**One thing at a time**: put the category and the entry in the subject, body can be empty.

| Subject                    | Logged as                              |
|----------------------------|----------------------------------------|
| `WATER 16oz`               | Water: 16oz                            |
| `MIGRAINE 6/10`            | Symptoms: migraine 6/10 (severity 6)   |
| `DIZZY 4/10`               | Symptoms: dizzy 4/10                   |
| `SINUS 5/10`               | Sinus pain: 5/10                       |
| `COFFEE`                   | Caffeine: coffee                       |
| `MONSTER 3/4`              | Caffeine: 3/4 monster (113 mg)         |
| `2 monsters`               | Caffeine: 2 monsters (300 mg)          |
| `ELECTROLYTES 1 serving`   | Electrolytes: 1 serving                |
| `RESCUE sumatriptan 50mg`  | Rescue meds: sumatriptan 50mg          |
| `LUNCH salad`              | Food: lunch: salad                     |
| `NAP 30 min`               | Nap: 30 min                            |
| `LEFT EARLY 2h migraine`   | Left early: 2h early: migraine         |
| `LEFT EARLY 1.5 hours`     | Left early: 1.5h early                 |
| `LEFT EARLY migraine`      | Left early: migraine (hours unknown)   |
| `BP 120/80`                | Blood pressure: 120/80                 |
| `HR 72`                    | Heart rate: 72 bpm                     |
| `HR 72 118`                | Heart rate: 72 to 118 bpm (+46), lying then standing |
| `O2 98`                    | O2: 98%                                |
| `MISC started new meds`    | Misc: started new meds                 |

Other words that work: `symptom`, `headache`, `vertigo`, `nausea`, `fatigue`,
`congestion`, `allergies`, `salt`, `lmnt`, `tea`, `soda`, `meds`, `triptan`,
`advil`, `tylenol`, `excedrin`, `meclizine`, `breakfast`, `dinner`, `snack`,
`napped`, `went home early`, `left work early`, `note`. `NAP` and `LEFT EARLY`
work on their own too. For leaving early, the first number is how many hours
early (`LEFT EARLY 2` = 2 hours); the weekly summary and doctor report add up
hours missed. Blood pressure, heart rate and O2 aren't in the check-in
template but can be sent any time (`blood pressure`, `pulse`, `heart rate`,
`spo2`, `oxygen` and `02` also work). Two heart rate numbers are read as
lying or sitting, then standing, and the rise is worked out for you.
Case doesn't matter.

**Short codes**: for when typing is too much. The subject (or a line of the
body) can be just codes:

| Code        | Logs                          |
|-------------|-------------------------------|
| `w16`       | Water 16oz                    |
| `e1`        | Electrolytes 1 serving        |
| `c1`        | Caffeine 1 cup                |
| `m7`        | Migraine 7/10                 |
| `d5`        | Dizzy 5/10                    |
| `v5`        | Vertigo 5/10                  |
| `n4`        | Nausea 4/10                   |
| `s4`        | Sinus pain 4/10               |
| `r sumatriptan` | Rescue med: sumatriptan   |
| `z30`       | Nap 30 min                    |
| `le2 migraine` | Left 2h early: migraine    |

Combine them: `w16 m7` logs both. Change or add codes in Settings → Tracking.

**Backdating**: end anything with `@time` to log it for when it happened:
`WATER 16oz @2pm`, `m6 @yesterday 4pm`, `d5 @mon noon`, `w8 @last night`.
`LOG @noon` backdates a whole email. A time later than now means yesterday.
The space before `@` is optional (`8/10@ 12 pm` works).

Water in oz, cups, ml or liters is added up for the daily total.

Monsters are converted to mg of caffeine at 150 mg a can (Monster Ultra
Sunrise): `3/4 monster`, `1 1/2 monsters`, `half a monster`, `monster 3/4`, `monster x2`
and plain `monster` work, singular or plural, with or without spaces (`3/4monster`),
in a subject or on a `Caffeine:` line. Add other drinks in Settings →
Tracking (e.g. `red bull = 80`). Daily caffeine is shown in mg when known.

## Reminders

Set the times and days in Settings → Reminders. Each reminder shows how much
water you've had against your daily goal, warns you if rescue meds are close to
10 days this month, and has a **Fill in a full log** button plus one-tap
buttons for common entries. The first reminder of the day also has **Napped
yesterday** and **Left early yesterday** buttons. You can also just reply and
type the lines.

- A reminder is skipped if you logged something in the last hour (adjustable).
- **Rough day**: tap the button in a reminder, email `ROUGH DAY`, or pick it
  in the window's "Today" box. You'll get only the last check-in of the day.
- **Pause today**: no more reminders today (`PAUSE`). `RESUME` undoes either.
- If the app wasn't running within 30 minutes of a reminder time, it's skipped.

If an email can't be understood, the app replies with the format (Settings →
"Reply to my log emails" can also be set to `always` or `never`).

## Weather and pollen

Set a ZIP code or "City, ST" in Settings → Tracking and the app records each
day's temperature, air pressure, humidity and rain (from Open-Meteo, free, no
account). It backfills the last 30 days the first time.

For pollen, sign the tracker Gmail up for your pollen alert emails and put the
sender's address (or just its domain) in Settings → Tracking. Each alert is
saved as that day's pollen report instead of being treated as a log.

## Weekly summary

Every Sunday at 6pm (adjustable, or off) you get an email with symptom and
migraine days compared with last week, worst day, rescue med days, water and
electrolyte averages, big pressure drops and high pollen days. Email `SUMMARY`
or use **Send email → Weekly summary now** to get one any time.

## Doctor visit report

**Doctor report** in the window makes a one-page report for the last 30 days,
90 days, 6 months or year: headline numbers, a severity chart with rescue med
days and water, a by-month table, most frequent symptoms, rescue meds, simple
pattern comparisons (pressure drops, low water, pollen, caffeine), a vitals
section (BP, heart rate with lying-to-standing rises, O2) and the full daily log. It opens in your browser; use Print → Save as PDF to bring or send
it. Reports are saved in the `reports` folder.

## In the window

- **Check inbox now**, **Send email** (reminder or weekly summary now)
- **Add entry**: log something directly without email (`@time` works here too).
- **Today**: switch between normal, rough day and paused.
- **Export CSV**: a spreadsheet of everything.
- Select a row and press **Delete** to remove it.
- Problems show in the status bar; details go to `tracker.log`.

## Tests

```
python -m unittest tests/test_parser.py
```
