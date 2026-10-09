/**
 * Symptom Tracker check-in reminders, sent by Gmail itself so they arrive even
 * when your PC is off. Runs in the tracker Gmail account at script.google.com.
 *
 * Setup: see README.md ("Reminders when your PC is off"). In short:
 *   1. Signed in as the tracker Gmail, create a project at script.google.com.
 *   2. Paste this file in, fill in CONFIG below, and save.
 *   3. Run `install` once and allow the permissions it asks for.
 *   4. In the desktop app, untick Settings → Reminders → "Send reminders from this PC".
 *
 * Emailing ROUGH DAY, PAUSE or RESUME to the tracker works here too.
 */

const CONFIG = {
  // Where reminders go (probably your work email).
  REMIND_TO: 'you@example.com',
  // The addresses you send logs from, so a recent log can skip a reminder and
  // ROUGH DAY / PAUSE / RESUME emails are noticed.
  MY_ADDRESSES: ['you@example.com'],
  TIMES: ['09:00', '12:00', '14:00'],          // 24-hour
  DAYS: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
  SKIP_IF_LOGGED_MINUTES: 60,                    // 0 = never skip
  WATER_GOAL_OZ: 64,
  // Reply with ideas from SUGGESTIONS soon after you log a symptom at those levels.
  SUGGEST_ON_LOG: true,
};

// What might help, by symptom and severity (out of 10). Edit freely.
const MIGRAINE_TIPS = ['mint gum', 'your menthol head stick', 'migraine glasses', 'a walk loop',
                       'electrolytes'];
const SUGGESTIONS = [
  { name: 'Sinus pain', match: /sinus|congest/i, code: /^s(\d+(?:\.\d+)?)$/i,
    at: 2, tips: ['an Advil', 'more water'], join: 'and' },
  { name: 'Migraine', match: /migraine|headache/i, code: /^m(\d+(?:\.\d+)?)$/i,
    at: 2, tips: MIGRAINE_TIPS, strongAt: 3.5, strongTip: 'a Nurtec' },
  { name: 'Dizziness', match: /dizz|vertigo|light-?headed/i, code: /^[dv](\d+(?:\.\d+)?)$/i,
    at: 2, tips: MIGRAINE_TIPS, strongAt: 3.5, strongTip: 'a Dramamine Less-Drowsy' },
];

const GRACE_MINUTES = 30;   // a reminder can go out up to this long after its time
const CHECK_EVERY_MINUTES = 10;

const TEMPLATE = 'Symptoms: \nSinus pain: \nWater: \nElectrolytes: \nCaffeine: \nFood: \n' +
                 'Rescue meds: \nMisc: \n';

/** Run once to start sending reminders. Safe to run again after editing CONFIG. */
function install() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'tick')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(CHECK_EVERY_MINUTES).create();
  Logger.log('Reminders on: ' + CONFIG.TIMES.join(', ') + ' on ' + CONFIG.DAYS.join(', ') +
             ' (' + Session.getScriptTimeZone() + ')');
}

/** Run to stop all reminders from this script. */
function uninstall() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  Logger.log('Reminders off.');
}

/** Run to get one reminder right now, to see what it looks like. */
function sendTestReminder() {
  sendReminder_(new Date(), todayMode_(new Date()), true);
}

/** Called every few minutes by the trigger that `install` creates. */
function tick() {
  const now = new Date();
  const tz = Session.getScriptTimeZone();
  if (CONFIG.SUGGEST_ON_LOG) {
    try {
      suggestOnNewLogs_(now);
    } catch (e) {  // never let suggestions stop reminders
      Logger.log('Suggestions failed: ' + e);
    }
  }
  if (CONFIG.DAYS.indexOf(Utilities.formatDate(now, tz, 'EEE')) < 0) return;

  const mode = todayMode_(now);
  if (mode === 'pause') return;
  let slots = CONFIG.TIMES.slice().sort();
  if (mode === 'rough') slots = slots.slice(-1);   // only the last check-in

  const props = PropertiesService.getScriptProperties();
  const today = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  slots.forEach((hhmm, i) => {
    const at = atTime_(now, hhmm);
    const key = 'sent ' + today + ' ' + hhmm;
    const late = (now - at) / 60000;
    if (late < 0 || late >= GRACE_MINUTES || props.getProperty(key)) return;
    props.setProperty(key, 'yes');   // mark first so a slow run can't send twice
    if (CONFIG.SKIP_IF_LOGGED_MINUTES > 0 && loggedSince_(new Date(now - CONFIG.SKIP_IF_LOGGED_MINUTES * 60000))) {
      Logger.log('Skipped ' + hhmm + ': you logged recently');
      return;
    }
    sendReminder_(at, mode, i === 0);
  });
  cleanUpOldMarks_(props, today);
}

// ---- helpers -----------------------------------------------------------------

/** Today's date at HH:MM in the script's time zone. */
function atTime_(now, hhmm) {
  const tz = Session.getScriptTimeZone();
  const day = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  const offset = Utilities.formatDate(now, tz, 'XXX');   // e.g. -04:00
  return new Date(day + 'T' + hhmm + ':00' + offset);
}

function fromMe_() {
  return '{' + CONFIG.MY_ADDRESSES.map(a => 'from:' + a).join(' ') + '}';
}

function loggedSince_(since) {
  const q = fromMe_() + ' after:' + Math.floor(since.getTime() / 1000);
  return GmailApp.search(q, 0, 1).length > 0;
}

/** 'normal', 'rough' or 'pause', from today's ROUGH DAY / PAUSE / RESUME emails. */
function todayMode_(now) {
  const midnight = atTime_(now, '00:00');
  const q = fromMe_() + ' after:' + Math.floor(midnight.getTime() / 1000) +
            ' {subject:rough subject:pause subject:resume subject:"no reminders"}';
  let latest = null, mode = 'normal';
  GmailApp.search(q, 0, 50).forEach(thread => {
    thread.getMessages().forEach(m => {
      if (m.getDate() < midnight) return;
      const s = m.getSubject().replace(/^\s*((re|fwd?)\s*:\s*)+/i, '').trim().toLowerCase();
      let found = null;
      if (/^rough\b/.test(s)) found = 'rough';
      else if (/^(pause|no reminders)\b/.test(s)) found = 'pause';
      else if (/^resume\b/.test(s)) found = 'normal';
      if (found && (!latest || m.getDate() > latest)) { latest = m.getDate(); mode = found; }
    });
  });
  return mode;
}

function cleanUpOldMarks_(props, today) {
  Object.keys(props.getProperties())
    .filter(k => k.indexOf('sent ') === 0 && k.slice(5, 15) < today)
    .forEach(k => props.deleteProperty(k));
}

function mailto_(to, subject, body) {
  let url = 'mailto:' + to + '?subject=' + encodeURIComponent(subject);
  if (body) url += '&body=' + encodeURIComponent(body);
  return url;
}

function button_(href, label, primary) {
  const bg = primary ? '#2f6f5e' : '#e8f0ed', fg = primary ? '#ffffff' : '#1f4a3f';
  return '<a href="' + href + '" style="display:inline-block;margin:4px 6px 4px 0;' +
         'padding:10px 14px;border-radius:8px;background:' + bg + ';color:' + fg + ';' +
         'text-decoration:none;font-weight:600">' + label + '</a>';
}

// ---- totals from your log emails ------------------------------------------------
// A light version of the desktop app's reading, so reminders can show water and
// medication counts while the PC is off. Entries backdated to another day are skipped.

const OZ_PER_ = { oz: 1, ounce: 1, ounces: 1, cup: 8, cups: 8, ml: 1 / 29.57, l: 33.81,
                  liter: 33.81, liters: 33.81, litre: 33.81, litres: 33.81 };
const RESCUE_RE_ = /^(rescue( meds?| medication)?|meds?|medication|triptan|sumatriptan|rizatriptan|ubrelvy|nurtec|tylenol|excedrin|meclizine|zofran|dramamine|bonine|ondansetron|r)\b/i;
const ADVIL_RE_ = /^(advil|ibuprofen|motrin|a\d)/i;

/** Your own lines from an email: the subject, then the body down to any quoted reply. */
function myLines_(message) {
  const lines = [message.getSubject().replace(/^\s*((re|fwd?)\s*:\s*)+/i, '')];
  for (const line of message.getPlainBody().split(/\r?\n/)) {
    if (/^\s*>/.test(line) || /^On .+wrote:\s*$/.test(line.trim()) || line.trim() === '--') break;
    lines.push(line);
  }
  return lines.map(l => l.trim()).filter(l => l && !/\b(yesterday|last night)\b|\bon\s+\d{1,2}\/\d{1,2}|@\s*\d{1,2}\/\d{1,2}/i.test(l));
}

function waterOz_(line) {
  let total = 0;
  for (const m of line.matchAll(/\bw(\d+(?:\.\d+)?)\b/gi)) total += Number(m[1]);   // short code w16
  const water = line.match(/^(water|h2o|drink|drank|fluids?)\s*:?\s*(.*)$/i);
  if (water) {
    for (const m of water[2].matchAll(/(\d+(?:\.\d+)?)\s*(oz|ounces?|cups?|ml|l|liters?|litres?)\b/gi)) {
      total += Number(m[1]) * OZ_PER_[m[2].toLowerCase()];
    }
  }
  return total;
}

/** Messages you sent since a given time, oldest first. */
function myMessagesSince_(since) {
  const q = fromMe_() + ' after:' + Math.floor(since.getTime() / 1000);
  const mine = CONFIG.MY_ADDRESSES.map(a => a.toLowerCase());
  const out = [];
  GmailApp.search(q, 0, 200).forEach(thread => thread.getMessages().forEach(m => {
    const from = (m.getFrom().match(/<([^>]+)>/) || [null, m.getFrom()])[1].toLowerCase();
    if (m.getDate() >= since && mine.indexOf(from) >= 0) out.push(m);
  }));
  return out.sort((a, b) => a.getDate() - b.getDate());
}

/** {waterOz, rescueDays, advilDays} for today and this month. */
function totals_(now) {
  const tz = Session.getScriptTimeZone();
  const today = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  const monthStart = atTime_(new Date(Utilities.formatDate(now, tz, 'yyyy-MM-01') + 'T12:00:00Z'), '00:00');
  let waterOz = 0;
  const rescue = new Set(), advil = new Set();
  myMessagesSince_(monthStart).forEach(m => {
    const day = Utilities.formatDate(m.getDate(), tz, 'yyyy-MM-dd');
    myLines_(m).forEach(line => {
      if (day === today) waterOz += waterOz_(line);
      const body = line.replace(/^[a-z ]+:\s*$/i, '');   // skip blank "Rescue meds:" template lines
      if (!body) return;
      if (RESCUE_RE_.test(body)) rescue.add(day);
      if (ADVIL_RE_.test(body)) advil.add(day);
    });
  });
  return { waterOz: Math.round(waterOz), rescueDays: rescue.size, advilDays: advil.size };
}

// ---- suggestions ---------------------------------------------------------------

/** Severity per SUGGESTIONS rule found in some lines: {Migraine: 4, ...}. Highest wins. */
function severities_(lines) {
  const found = {};
  lines.forEach(line => {
    line.split(/\s+/).forEach(token => {   // short codes like m4 or s2.5
      SUGGESTIONS.forEach(rule => {
        const m = token.match(rule.code);
        if (m) found[rule.name] = Math.max(found[rule.name] || 0, Number(m[1]));
      });
    });
    const sev = line.match(/(\d+(?:\.\d+)?)\s*\/\s*10\b/);
    if (!sev) return;
    // "Sinus pain: 3/10", "MIGRAINE 4/10", "Symptoms: dizzy 3/10, headache 2/10"
    line.split(/[,;]/).forEach(part => {
      const s = part.match(/(\d+(?:\.\d+)?)\s*\/\s*10\b/);
      if (!s) return;
      SUGGESTIONS.forEach(rule => {
        if (rule.match.test(part)) found[rule.name] = Math.max(found[rule.name] || 0, Number(s[1]));
      });
    });
  });
  return found;
}

/** Sentences of ideas for the given severities, or []. */
function suggestions_(found, totals) {
  const out = [];
  SUGGESTIONS.forEach(rule => {
    const level = found[rule.name];
    if (level === undefined || level < rule.at) return;
    let line = rule.name + ' ' + level + '/10: ' +
               'try ' + listOf_(rule.tips, rule.join || 'or') + '.';
    if (rule.strongAt && level >= rule.strongAt) {
      line += ' Since it\'s ' + rule.strongAt + ' or higher, this may be a good time for ' + rule.strongTip + '.';
      if (totals && totals.rescueDays >= 8) {
        line += ' (Rescue meds have been needed on ' + totals.rescueDays + ' days this month.)';
      }
    }
    if (/advil/i.test(rule.tips.join(' ')) && totals && totals.advilDays >= 12) {
      line += ' (Advil on ' + totals.advilDays + ' days this month already.)';
    }
    out.push(line);
  });
  return out;
}

function listOf_(items, joiner) {
  return items.length < 2 ? items.join('') :
    items.slice(0, -1).join(', ') + (items.length > 2 ? ',' : '') + ' ' + joiner + ' ' + items[items.length - 1];
}

/** Reply to each new log email with ideas when a symptom is at or above its level. */
function suggestOnNewLogs_(now) {
  const props = PropertiesService.getScriptProperties();
  const since = new Date(now - 30 * 60000);   // only fresh logs, never a backlog
  let totals = null;
  myMessagesSince_(since).forEach(m => {
    const key = 'suggested ' + m.getId();
    if (props.getProperty(key)) return;
    props.setProperty(key, Utilities.formatDate(now, 'UTC', 'yyyy-MM-dd'));
    const found = severities_(myLines_(m));
    if (!Object.keys(found).length) return;
    totals = totals || totals_(now);
    const ideas = suggestions_(found, totals);
    if (!ideas.length) return;
    m.reply('Logged. A few things that might help:\n\n' + ideas.map(i => '• ' + i).join('\n') + '\n', {
      htmlBody: '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px">' +
                '<p>Logged. A few things that might help:</p><ul>' +
                ideas.map(i => '<li style="margin-bottom:4px">' + i + '</li>').join('') + '</ul></div>',
    });
  });
  // Forget marks older than two days.
  const cutoff = Utilities.formatDate(new Date(now - 2 * 86400000), 'UTC', 'yyyy-MM-dd');
  Object.entries(props.getProperties())
    .filter(([k, v]) => k.indexOf('suggested ') === 0 && v < cutoff)
    .forEach(([k]) => props.deleteProperty(k));
}

/** Latest severity per rule from today's logs, for reminders. */
function todaysLatestSeverities_(now) {
  const latest = {};
  myMessagesSince_(atTime_(now, '00:00')).forEach(m => {   // oldest first, so later logs win
    Object.assign(latest, severities_(myLines_(m)));
  });
  return latest;
}

/** Lines about water and medication to put at the top of a reminder. */
function notes_(now) {
  const t = totals_(now);
  const goal = CONFIG.WATER_GOAL_OZ;
  const hour = Number(Utilities.formatDate(now, Session.getScriptTimeZone(), 'H')) +
               Number(Utilities.formatDate(now, Session.getScriptTimeZone(), 'm')) / 60;
  const pace = goal * Math.min(Math.max((hour - 8) / 12, 0), 1);   // goal spread over 8am-8pm
  let water = 'Water so far today: ' + t.waterOz + ' of ' + goal + ' oz.';
  if (t.waterOz >= goal) water += ' Goal reached!';
  else if (t.waterOz < pace * 0.75) water += ' A little behind, a glass now would help.';
  const notes = [water];
  if (t.rescueDays >= 8) {
    notes.push('Heads up: rescue meds on ' + t.rescueDays + ' days this month. ' +
               '10+ days a month can cause rebound headaches.');
  }
  if (t.advilDays >= 12) {
    notes.push('Heads up: Advil on ' + t.advilDays + ' days this month. ' +
               '15+ days a month of pain relievers can cause rebound headaches.');
  }
  suggestions_(todaysLatestSeverities_(now), t).forEach(idea => notes.push('Might help: ' + idea));
  return { notes: notes, progress: goal ? Math.min(t.waterOz / goal, 1) : 0 };
}

function sendReminder_(at, mode, first) {
  const tracker = Session.getEffectiveUser().getEmail();
  const label = Utilities.formatDate(at, Session.getScriptTimeZone(), 'h:mm a');
  const rough = mode === 'rough';
  const intro = rough ? 'Rough day, so this is the only check-in today. Log just what you can.'
                      : 'Time to check in.';
  const quick = [['+ 8oz water', 'WATER 8oz'], ['+ 16oz water', 'WATER 16oz'],
                 ['Electrolytes', 'ELECTROLYTES 1 serving'], ['Caffeine', 'CAFFEINE '],
                 ['Migraine', 'MIGRAINE /10'], ['Dizzy', 'DIZZY /10'], ['Sinus pain', 'SINUS /10'],
                 ['Rescue med', 'RESCUE '], ['Advil', 'ADVIL 2'], ['Food', 'FOOD '], ['Nap', 'NAP '],
                 ['Leaving early', 'LEFT EARLY 2h '], ['Note', 'MISC ']];
  const yesterday = first ? [['Napped yesterday', 'NAP @yesterday'],
                             ['Left early yesterday', 'LEFT EARLY 2h @yesterday']] : [];
  const day = rough ? [['Resume normal', 'RESUME']]
                    : [['Rough day (1 check-in)', 'ROUGH DAY'], ['Pause today', 'PAUSE']];
  const buttons = list => list.map(([l, s]) => button_(mailto_(tracker, s), l)).join('');
  let info = { notes: [], progress: null };
  try {
    info = notes_(new Date());
  } catch (e) {  // never let the totals stop a reminder
    Logger.log('Totals failed: ' + e);
  }
  const bar = info.progress === null ? '' :
    '<div style="background:#e3ecef;border-radius:6px;height:10px;width:260px;margin:4px 0 10px">' +
    '<div style="background:#2e86c1;border-radius:6px;height:10px;width:' +
    Math.round(info.progress * 100) + '%"></div></div>';

  const html =
    '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#1c1c1c">' +
    '<p style="margin-bottom:6px"><b>' + intro + '</b></p>' +
    info.notes.map(n => '<p style="margin:2px 0">' + n + '</p>').join('') + bar +
    '<p>Tap below to open a fill-in-the-blanks log, or just reply to this email.</p>' +
    '<p>' + button_(mailto_(tracker, 'LOG', TEMPLATE), 'Fill in a full log', true) + '</p>' +
    '<p style="margin-bottom:2px;color:#555">Or add just one thing:</p><p>' + buttons(quick) + '</p>' +
    (yesterday.length ? '<p style="margin-bottom:2px;color:#555">Anything from yesterday?</p><p>' +
                        buttons(yesterday) + '</p>' : '') +
    '<p style="margin-bottom:2px;color:#555">How\'s today going?</p><p>' + buttons(day) + '</p>' +
    '<p style="color:#555;font-size:13px">Short codes like <b>w16</b>, <b>m7</b> and <b>le2 migraine</b> ' +
    'work as the subject. Add @time to backdate, e.g. <b>w16 @2pm</b>.</p></div>';
  const text = intro + '\n' + info.notes.join('\n') + '\n\nReply to this email and fill in whatever applies. ' +
               'Leave anything blank to skip it.\n\n' + TEMPLATE +
               '\nSubject ROUGH DAY = only one check-in today, PAUSE = none today, RESUME = back to normal.\n';

  GmailApp.sendEmail(CONFIG.REMIND_TO, 'Symptom check-in (' + label + ')', text, { htmlBody: html });
}
