// Reads Apple Calendar events in a date range and prints them as JSON.
//
// Run:  osascript -l JavaScript calendar_events.js <startISO> <endISO>
//   e.g. osascript -l JavaScript calendar_events.js 2026-08-30T00:00:00Z 2026-09-14T00:00:00Z
//
// Strategy 1: EventKit (fast, complete, works with iCloud/Exchange/Google
//             accounts already in Calendar.app).
// Strategy 2: scripting Calendar.app directly, if EventKit access is refused.
//
// The first run triggers the macOS "wants to access your calendar" prompt,
// attributed to whatever launched this (Coffee Chat Tracker / Terminal).

ObjC.import('EventKit');
ObjC.import('Foundation');

function isoString(nsdate) {
  if (!nsdate || nsdate.js === undefined && !nsdate) return null;
  try {
    var f = $.NSISO8601DateFormatter.alloc.init;
    return ObjC.unwrap(f.stringFromDate(nsdate));
  } catch (e) {
    return null;
  }
}

function dateFromISO(text) {
  var f = $.NSISO8601DateFormatter.alloc.init;
  return f.dateFromString(text);
}

function pump(seconds) {
  $.NSRunLoop.currentRunLoop.runUntilDate(
    $.NSDate.dateWithTimeIntervalSinceNow(seconds)
  );
}

var AVAILABILITY = { 0: 'notsupported', 1: 'busy', 2: 'free', 3: 'tentative', 4: 'unavailable' };
var STATUS = { 0: 'none', 1: 'confirmed', 2: 'tentative', 3: 'canceled' };

function viaEventKit(startISO, endISO) {
  var store = $.EKEventStore.alloc.init;
  var granted = false;
  var finished = false;

  var callback = function (ok, _err) { granted = ok; finished = true; };

  var requested = false;
  try {
    // macOS 14+
    store.requestFullAccessToEventsCompletion(callback);
    requested = true;
  } catch (e) {
    requested = false;
  }
  if (!requested) {
    store.requestAccessToEntityTypeCompletion($.EKEntityTypeEvent, callback);
  }

  var waited = 0;
  while (!finished && waited < 60) { pump(0.2); waited += 0.2; }

  if (!granted) {
    throw new Error('calendar-access-denied');
  }

  var start = dateFromISO(startISO);
  var end = dateFromISO(endISO);
  if (!start || !end) throw new Error('bad-date-range');

  var predicate = store.predicateForEventsWithStartDateEndDateCalendars(start, end, $());
  var events = store.eventsMatchingPredicate(predicate);
  var count = events.count;
  var out = [];

  for (var i = 0; i < count; i++) {
    var ev = events.objectAtIndex(i);
    var status = STATUS[ev.status] || 'none';
    if (status === 'canceled') continue;
    var calTitle = '';
    try { calTitle = ObjC.unwrap(ev.calendar.title) || ''; } catch (e) {}
    var title = '';
    try { title = ObjC.unwrap(ev.title) || '(no title)'; } catch (e) { title = '(no title)'; }
    out.push({
      title: title,
      calendar: calTitle,
      start: isoString(ev.startDate),
      end: isoString(ev.endDate),
      all_day: ev.isAllDay ? true : false,
      status: status,
      availability: AVAILABILITY[ev.availability] || 'busy',
      source: 'eventkit'
    });
  }
  return out;
}

function viaCalendarApp(startISO, endISO) {
  var Calendar = Application('Calendar');
  Calendar.includeStandardAdditions = true;
  var start = new Date(startISO);
  var end = new Date(endISO);
  var out = [];
  var calendars = Calendar.calendars();
  for (var c = 0; c < calendars.length; c++) {
    var cal = calendars[c];
    var name = '';
    try { name = cal.name(); } catch (e) { name = ''; }
    var events;
    try {
      events = cal.events.whose({
        _and: [{ startDate: { _greaterThan: start } }, { startDate: { _lessThan: end } }]
      })();
    } catch (e) {
      continue;
    }
    for (var i = 0; i < events.length; i++) {
      try {
        out.push({
          title: events[i].summary(),
          calendar: name,
          start: events[i].startDate().toISOString(),
          end: events[i].endDate().toISOString(),
          all_day: events[i].alldayEvent(),
          status: 'confirmed',
          availability: 'busy',
          source: 'calendar-app'
        });
      } catch (e) { /* skip unreadable event */ }
    }
  }
  return out;
}

function run(argv) {
  var startISO = argv[0];
  var endISO = argv[1];
  if (!startISO || !endISO) {
    return JSON.stringify({ ok: false, error: 'usage: calendar_events.js <startISO> <endISO>' });
  }
  try {
    return JSON.stringify({ ok: true, events: viaEventKit(startISO, endISO) });
  } catch (primaryError) {
    try {
      return JSON.stringify({
        ok: true,
        events: viaCalendarApp(startISO, endISO),
        note: 'EventKit unavailable (' + primaryError.message + '); read Calendar.app directly.'
      });
    } catch (fallbackError) {
      return JSON.stringify({
        ok: false,
        error: String(primaryError.message || primaryError),
        fallback_error: String(fallbackError.message || fallbackError)
      });
    }
  }
}
