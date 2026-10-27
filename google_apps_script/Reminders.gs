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
  SKIP_IF_LOGGED_MINUTES: 0,                     // skip a reminder if you logged this recently; 0 = always send
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
    at: 2, tips: ['a visual break', 'a walk', 'more water'], join: 'and',
    strongAt: 3.5, strongTip: 'a Dramamine Less-Drowsy' },
];

const GRACE_MINUTES = 30;   // a reminder can go out up to this long after its time
const CHECK_EVERY_MINUTES = 10;

const TEMPLATE = 'Symptoms: \nSinus pain: \nFatigue: \nWater: \nElectrolytes: \nCaffeine: \nFood: \n' +
                 'Rescue meds: \nMisc: \n';

/** Stop with a clear message if CONFIG still has the example addresses. */
function checkConfig_() {
  const all = [CONFIG.REMIND_TO].concat(CONFIG.MY_ADDRESSES).join(' ');
  if (/@example\.com/i.test(all)) {
    throw new Error('CONFIG still has you@example.com. Put your real addresses in REMIND_TO ' +
                    'and MY_ADDRESSES at the top of the script, then save.');
  }
}

/** Run once to start sending reminders. Safe to run again after editing CONFIG. */
function install() {
  checkConfig_();
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
  checkConfig_();
  Logger.log('Building a test reminder...');
  sendReminder_(new Date(), todayMode_(new Date()), true);
  Logger.log('Sent to ' + CONFIG.REMIND_TO + '.');
}

/** Run to email yourself the "Today so far" summary right now. */
function sendTestToday() {
  checkConfig_();
  Logger.log('Building today so far...');
  const s = todaySoFar_(new Date());
  GmailApp.sendEmail(CONFIG.REMIND_TO, s.subject, s.text, { htmlBody: s.html });
  Logger.log('Sent to ' + CONFIG.REMIND_TO + '.');
}

/** Called every few minutes by the trigger that `install` creates. */
function tick() {
  checkConfig_();   // shows up under Executions as a failed run until fixed
  const now = new Date();
  const tz = Session.getScriptTimeZone();
  try {
    answerTodayRequests_(now);
  } catch (e) {  // never let this stop reminders
    Logger.log('Today-so-far reply failed: ' + e);
  }
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

/**
 * Your own lines from an email: the subject, then the body down to any quoted reply.
 * Lines backdated to another day are left out, and so is the whole email when its
 * subject is (e.g. "FOOD @10/23" with "banana" underneath).
 */
function myLines_(message) {
  const sent = message.getDate();
  const subject = message.getSubject().replace(/^\s*((re|fwd?)\s*:\s*)+/i, '').trim();
  if (otherDay_(subject, sent)) return [];
  const lines = [subject];
  for (const line of message.getPlainBody().split(/\r?\n/)) {
    if (/^\s*>/.test(line) || /^On .+wrote:\s*$/.test(line.trim()) || line.trim() === '--') break;
    lines.push(line);
  }
  return lines.map(l => l.trim()).filter(l => l && !otherDay_(l, sent));
}

const MONTHS_ = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/** True if a line is backdated to a day other than the one it was sent: @yesterday, @10/23, on oct 23. */
function otherDay_(line, sent) {
  if (/@\s*(yesterday|yday|yest|last night)\b|\b(yesterday|last night)\b/i.test(line)) return true;
  const sentMD = Utilities.formatDate(sent, Session.getScriptTimeZone(), 'M/d');
  const num = line.match(/(?:@|\bon\s)\s*(\d{1,2})\/(\d{1,2})\b/i);
  if (num) return Number(num[1]) + '/' + Number(num[2]) !== sentMD;
  const named = line.match(/(?:@|\bon\s)\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})\b/i);
  if (named) return (MONTHS_.indexOf(named[1].toLowerCase()) + 1) + '/' + Number(named[2]) !== sentMD;
  return false;
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

/**
 * Messages you sent since a given time, oldest first. Gmail calls are slow, so a
 * run fetches each stretch of mail once (in one batch) and reuses it.
 */
let fetched_ = null;   // {since, messages} for this run
function myMessagesSince_(since) {
  if (!fetched_ || since < fetched_.since) {
    const q = fromMe_() + ' after:' + Math.floor(since.getTime() / 1000);
    const mine = CONFIG.MY_ADDRESSES.map(a => a.toLowerCase());
    const out = [];
    GmailApp.getMessagesForThreads(GmailApp.search(q, 0, 200)).forEach(msgs => msgs.forEach(m => {
      const date = m.getDate();
      if (date < since) return;
      const from = (m.getFrom().match(/<([^>]+)>/) || [null, m.getFrom()])[1].toLowerCase();
      if (mine.indexOf(from) >= 0) out.push(m);
    }));
    out.sort((a, b) => a.getDate() - b.getDate());
    fetched_ = { since: since, messages: out };
  }
  return fetched_.messages.filter(m => m.getDate() >= since);
}

/**
 * {waterOz, rescueDays, advilDays} for today and this month. Earlier days of the
 * month are remembered, so only today's emails are read on each run.
 */
function totals_(now) {
  const tz = Session.getScriptTimeZone();
  const today = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  const month = today.slice(0, 7);
  const props = PropertiesService.getScriptProperties();
  let saved = null;
  try {
    saved = JSON.parse(props.getProperty('med days ' + month) || 'null');
  } catch (e) {}
  if (!saved || saved.through > today) saved = { through: month + '-01', rescue: [], advil: [] };
  let waterOz = 0;
  const rescue = new Set(saved.rescue), advil = new Set(saved.advil);
  myMessagesSince_(atTime_(new Date(saved.through + 'T12:00:00Z'), '00:00')).forEach(m => {
    const day = Utilities.formatDate(m.getDate(), tz, 'yyyy-MM-dd');
    myLines_(m).forEach(line => {
      if (day === today) waterOz += waterOz_(line);
      const body = line.replace(/^[a-z ]+:\s*$/i, '');   // skip blank "Rescue meds:" template lines
      if (!body) return;
      if (RESCUE_RE_.test(body)) rescue.add(day);
      if (ADVIL_RE_.test(body)) advil.add(day);
    });
  });
  // Days before today are finished, so remember them.
  props.setProperty('med days ' + month, JSON.stringify({
    through: today,
    rescue: Array.from(rescue).filter(d => d < today),
    advil: Array.from(advil).filter(d => d < today),
  }));
  Object.keys(props.getProperties())
    .filter(k => k.indexOf('med days ') === 0 && k !== 'med days ' + month)
    .forEach(k => props.deleteProperty(k));
  return { waterOz: Math.round(waterOz), rescueDays: rescue.size, advilDays: advil.size };
}

// ---- suggestions ---------------------------------------------------------------

/** Severity per SUGGESTIONS rule found in some lines: {Migraine: 4, ...}. Highest wins. */
function severities_(lines, rules) {
  rules = rules || SUGGESTIONS;
  const found = {};
  lines.forEach(line => {
    line.split(/\s+/).forEach(token => {   // short codes like m4 or s2.5
      rules.forEach(rule => {
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
      rules.forEach(rule => {
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
  const notes = [];
  if (t.rescueDays >= 8) {
    notes.push('Heads up: rescue meds on ' + t.rescueDays + ' days this month. ' +
               '10+ days a month can cause rebound headaches.');
  }
  if (t.advilDays >= 12) {
    notes.push('Heads up: Advil on ' + t.advilDays + ' days this month. ' +
               '15+ days a month of pain relievers can cause rebound headaches.');
  }
  return { water: water, notes: notes, ideas: suggestions_(todaysLatestSeverities_(now), t),
           progress: goal ? Math.min(t.waterOz / goal, 1) : 0 };
}

// ---- "Today so far" ---------------------------------------------------------------
// Email the tracker with the subject TODAY (or STATUS / SO FAR) to get a summary back.

const TODAY_REQUEST_RE_ = /^(today( so far)?|status|so far|how('?s| is) today( going)?)\??$/i;
const FATIGUE_RULE_ = { name: 'Fatigue', match: /fatigu|tired|exhaust/i, code: /^f(\d+(?:\.\d+)?)$/i };
const COMMAND_RE_ = /^(rough( day)?|pause( today)?|no reminders|resume|summary|weekly summary)$/i;

function isTodayRequest_(message) {
  const s = message.getSubject().replace(/^\s*((re|fwd?)\s*:\s*)+/i, '').trim();
  return TODAY_REQUEST_RE_.test(s);
}

function answerTodayRequests_(now) {
  const props = PropertiesService.getScriptProperties();
  myMessagesSince_(new Date(now - 30 * 60000)).forEach(m => {
    if (!isTodayRequest_(m)) return;
    const key = 'today ' + m.getId();
    if (props.getProperty(key)) return;
    props.setProperty(key, Utilities.formatDate(now, 'UTC', 'yyyy-MM-dd'));
    const s = todaySoFar_(now);
    m.reply(s.text, { htmlBody: s.html });
  });
}

/** Latest and highest rating today per symptom: {Migraine: {latest, peak, at}}. */
function todaysRatings_(messages, tz) {
  const rules = SUGGESTIONS.concat([FATIGUE_RULE_]);
  const out = {};
  messages.forEach(m => {
    const found = severities_(myLines_(m), rules);
    Object.keys(found).forEach(name => {
      const r = out[name] || { peak: 0 };
      r.latest = found[name];
      r.peak = Math.max(r.peak, found[name]);
      r.at = Utilities.formatDate(m.getDate(), tz, 'h:mm a');
      out[name] = r;
    });
  });
  return out;
}

/**
 * What an email logged, tidied for reading: lines your mail app wrapped are joined
 * back up, and a bare subject like FOOD is put together with what you wrote under
 * it ("Food: banana"). The LOG and check-in subjects and blank template lines are left out.
 */
function logEntries_(message) {
  const lines = myLines_(message);
  let subject = message.getSubject().replace(/^\s*((re|fwd?)\s*:\s*)+/i, '').trim();
  if (lines[0] === subject) lines.shift();
  else subject = '';
  subject = subject.replace(/^@\s*\S+(\s+\d{1,2}(:\d\d)?\s*(am|pm))?\s+/i, '');   // "@2pm FOOD" -> "FOOD"
  const body = [];
  lines.forEach(line => {
    if (/^[a-z ]+:\s*$/i.test(line) || COMMAND_RE_.test(line)) return;
    const prev = body[body.length - 1];
    // Mail apps wrap long lines at about 70 characters; a long line followed by
    // one that isn't a new "Label:" line or code is a single wrapped sentence.
    if (prev && prev.length >= 60 && !/^[A-Za-z ]+:/.test(line) && !/^[A-Z]{2,}\b/.test(line)) {
      body[body.length - 1] = prev + ' ' + line;
    } else {
      body.push(line);
    }
  });
  const pretty = s => s.replace(/^([A-Z][A-Z ]*[A-Z])\b/, w => w.charAt(0) + w.slice(1).toLowerCase())
                       .replace(/^Misc\b/, 'Note')
                       .replace(/^a(\d+(?:\.\d+)?)$/i, 'Advil x$1');   // short code a2
  if (/^(log|symptom check-in.*)$/i.test(subject) || COMMAND_RE_.test(subject) || !subject) {
    return body.map(pretty);
  }
  if (/^[a-z ]+$/i.test(subject) && body.length) {   // a bare label, e.g. FOOD + "banana"
    return [pretty(subject.trim()) + ': ' + body.join(' ')];
  }
  return [pretty(subject)].concat(body.map(pretty));
}

/** {subject, text, html} summarising today's logs. */
function todaySoFar_(now) {
  const tz = Session.getScriptTimeZone();
  const messages = myMessagesSince_(atTime_(now, '00:00')).filter(m => !isTodayRequest_(m));
  const t = totals_(now);
  const goal = CONFIG.WATER_GOAL_OZ;
  const ratings = todaysRatings_(messages, tz);
  // Sort what you logged into a few groups. Water and ratings are already in the
  // totals above, so only what they leave out is listed.
  const meds = [], food = [], caffeine = [], electrolytes = [], notes = [];
  messages.forEach(m => {
    const time = Utilities.formatDate(m.getDate(), tz, 'h:mm a');
    logEntries_(m).forEach(entry => {
      const parts = entry.match(/^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$/) ||
                    entry.match(/^(food|caffeine|electrolytes|note|nap|left early|water|sinus|migraine|dizzy|fatigue)\b\s*(.*)$/i);
      const label = parts ? parts[1].toLowerCase() : '';
      const value = parts ? parts[2].trim() : entry;
      if (RESCUE_RE_.test(entry) || ADVIL_RE_.test(entry)) {
        meds.push((label === 'rescue meds' ? value : entry.replace(/^advil:?\s*x?/i, 'Advil ')) + ' (' + time + ')');
      } else if (/^([a-z]{1,3}\d+(\.\d+)?\s*)+$/i.test(entry) || waterOz_(entry) > 0 || /^(water|h2o)$/.test(label)) {
        return;   // short codes and water: counted above
      } else if (!value) {
        return;
      } else if (/^(sinus( pain)?|migraine|dizzy|dizziness|fatigue)$/.test(label) && /^\d+(\.\d+)?\s*\/\s*10$/.test(value)) {
        return;   // a rating: shown above
      } else if (label === 'food') {
        food.push(value + ' (' + time + ')');
      } else if (label === 'caffeine') {
        caffeine.push(value + ' (' + time + ')');
      } else if (label === 'electrolytes') {
        electrolytes.push(value + ' (' + time + ')');
      } else if (/^(note|misc|symptoms?)$/.test(label)) {
        notes.push(time + '  ' + value);
      } else {
        notes.push(time + '  ' + entry);
      }
    });
  });

  const lines = [];
  lines.push('Water: ' + t.waterOz + ' of ' + goal + ' oz' + (t.waterOz >= goal ? ' (goal reached!)' : ''));
  const names = Object.keys(ratings);
  if (names.length) {
    names.forEach(n => {
      const r = ratings[n];
      lines.push(n + ': ' + r.latest + '/10 at ' + r.at + (r.peak > r.latest ? ' (peaked at ' + r.peak + '/10)' : ''));
    });
  } else {
    lines.push('No symptom ratings logged yet today.');
  }
  lines.push('Meds today: ' + (meds.length ? meds.join('; ') : 'none logged'));
  if (food.length) lines.push('Food: ' + food.join(', '));
  if (caffeine.length) lines.push('Caffeine: ' + caffeine.join(', '));
  if (electrolytes.length) lines.push('Electrolytes: ' + electrolytes.join(', '));
  lines.push('This month: rescue meds on ' + t.rescueDays + ' day' + (t.rescueDays === 1 ? '' : 's') +
             ', Advil on ' + t.advilDays + ' day' + (t.advilDays === 1 ? '' : 's'));
  const latest = {};
  names.forEach(n => { latest[n] = ratings[n].latest; });
  const ideas = suggestions_(latest, t);

  const dateLabel = Utilities.formatDate(now, tz, 'EEEE, MMM d');
  const subject = 'Today so far (' + Utilities.formatDate(now, tz, 'h:mm a') + ')';
  const text = 'Today so far, ' + dateLabel + '\n\n' + lines.join('\n') +
               (ideas.length ? '\n\nMight help:\n' + ideas.map(i => '- ' + i).join('\n') : '') +
               (notes.length ? '\n\nNotes:\n' + notes.join('\n') : '') + '\n';
  const progress = goal ? Math.min(t.waterOz / goal, 1) : 0;
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const html =
    '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#1c1c1c">' +
    '<p style="margin-bottom:6px"><b>Today so far</b> <span style="color:#555">' + dateLabel + '</span></p>' +
    '<p style="margin:2px 0">' + esc(lines[0]) + '</p>' +
    '<div style="background:#e3ecef;border-radius:6px;height:10px;width:260px;margin:4px 0 10px">' +
    '<div style="background:#2e86c1;border-radius:6px;height:10px;width:' + Math.round(progress * 100) +
    '%"></div></div>' +
    lines.slice(1).map(l => '<p style="margin:2px 0">' + esc(l) + '</p>').join('') +
    (ideas.length ? '<p style="margin:10px 0 2px"><b>Might help</b></p><ul style="margin-top:2px">' +
                    ideas.map(i => '<li style="margin-bottom:4px">' + esc(i) + '</li>').join('') + '</ul>' : '') +
    (notes.length ? '<p style="margin:12px 0 2px"><b>Notes</b></p><table style="border-collapse:collapse;font-size:14px">' +
      notes.map(l => {
        const sp = l.indexOf('  ');
        return '<tr><td style="padding:2px 10px 2px 0;color:#555;white-space:nowrap;vertical-align:top">' +
               esc(l.slice(0, sp)) + '</td><td style="padding:2px 0">' + esc(l.slice(sp + 2)) + '</td></tr>';
      }).join('') + '</table>' : '') + '</div>';
  return { subject: subject, text: text, html: html };
}

function sendReminder_(at, mode, first) {
  const tracker = Session.getEffectiveUser().getEmail();
  const label = Utilities.formatDate(at, Session.getScriptTimeZone(), 'h:mm a');
  const rough = mode === 'rough';
  const intro = rough ? 'Rough day, so this is the only check-in today. Log just what you can.'
                      : 'Time to check in.';
  const quick = [['+ 8oz water', 'WATER 8oz'], ['+ 16oz water', 'WATER 16oz'],
                 ['Electrolytes', 'ELECTROLYTES 1 serving'], ['Caffeine', 'CAFFEINE '],
                 ['Migraine', 'MIGRAINE /10'], ['Dizzy', 'DIZZY /10'], ['Sinus pain', 'SINUS /10'], ['Fatigue', 'FATIGUE /10'],
                 ['Rescue med', 'RESCUE '], ['Advil', 'ADVIL 2'], ['Food', 'FOOD '], ['Nap', 'NAP '],
                 ['Leaving early', 'LEFT EARLY 2h '], ['Note', 'MISC ']];
  const yesterday = first ? [['Napped yesterday', 'NAP @yesterday'],
                             ['Left early yesterday', 'LEFT EARLY 2h @yesterday']] : [];
  const day = (rough ? [['Resume normal', 'RESUME']]
                     : [['Rough day (1 check-in)', 'ROUGH DAY'], ['Pause today', 'PAUSE']])
    .concat([['Today so far', 'TODAY']]);
  const buttons = list => list.map(([l, s]) => button_(mailto_(tracker, s), l)).join('');
  let info = { water: '', notes: [], ideas: [], progress: null };
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
    (info.water ? '<p style="margin:2px 0">' + info.water + '</p>' : '') + bar +
    info.notes.map(n => '<p style="margin:2px 0">' + n + '</p>').join('') +
    (info.ideas.length ? '<p style="margin:10px 0 2px"><b>Might help</b></p><ul style="margin-top:2px">' +
                         info.ideas.map(i => '<li style="margin-bottom:4px">' + i + '</li>').join('') + '</ul>' : '') +
    '<p>Tap below to open a fill-in-the-blanks log, or just reply to this email.</p>' +
    '<p>' + button_(mailto_(tracker, 'LOG', TEMPLATE), 'Fill in a full log', true) + '</p>' +
    '<p style="margin-bottom:2px;color:#555">Or add just one thing:</p><p>' + buttons(quick) + '</p>' +
    (yesterday.length ? '<p style="margin-bottom:2px;color:#555">Anything from yesterday?</p><p>' +
                        buttons(yesterday) + '</p>' : '') +
    '<p style="margin-bottom:2px;color:#555">How\'s today going?</p><p>' + buttons(day) + '</p>' +
    '<p style="color:#555;font-size:13px">Short codes like <b>w16</b>, <b>m7</b> and <b>le2 migraine</b> ' +
    'work as the subject. Add @time to backdate, e.g. <b>w16 @2pm</b>.</p></div>';
  const text = intro + '\n' + [info.water].concat(info.notes).filter(Boolean).join('\n') +
               (info.ideas.length ? '\n\nMight help:\n' + info.ideas.map(i => '- ' + i).join('\n') : '') +
               '\n\nReply to this email and fill in whatever applies. ' +
               'Leave anything blank to skip it.\n\n' + TEMPLATE +
               '\nSubject ROUGH DAY = only one check-in today, PAUSE = none today, RESUME = back to normal.\n';

  GmailApp.sendEmail(CONFIG.REMIND_TO, 'Symptom check-in (' + label + ')', text, { htmlBody: html });
}
