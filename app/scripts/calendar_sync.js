// Edits Apple Calendar in place through EventKit. Used when a chat is
// confirmed, rescheduled or cancelled — so the calendar changes rather than
// gaining imported copies (Calendar.app never matches an imported .ics to an
// earlier import, so a file cannot move or cancel anything).
//
// Run: osascript -l JavaScript calendar_sync.js <json>
//   {
//     "delete": [{"prefix": "<title starts with>", "start": iso, "end": iso|null}],
//     "upsert": {"prefix": "<title starts with>", "match": {"start": iso, "end": iso|null}|null,
//                "title": "...", "start": iso, "end": iso, "notes": "..."},
//     "ensure": [{"prefix": ..., "title": ..., "start": iso, "end": iso, "notes": ...}]
//   }
// "ensure" creates each event unless one with that prefix and those exact
// times is already there (used for coffee-chat holds).
// "end": null matches on start time alone. An upsert that finds nothing to
// move creates the event in the default calendar.

ObjC.import('EventKit');
ObjC.import('Foundation');

function pump(s) {
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(s));
}
function ms(iso) { return new Date(iso).getTime(); }
function nsdate(t) { return $.NSDate.dateWithTimeIntervalSince1970(t / 1000); }

function access(store) {
  var granted = false, finished = false;
  var cb = function (ok, _e) { granted = ok; finished = true; };
  try { store.requestFullAccessToEventsCompletion(cb); }
  catch (e) { store.requestAccessToEntityTypeCompletion($.EKEntityTypeEvent, cb); }
  var waited = 0;
  while (!finished && waited < 60) { pump(0.2); waited += 0.2; }
  if (!granted) throw new Error('calendar-access-denied');
}

function run(argv) {
  try {
    var req = JSON.parse(argv[0]);
    var dels = req['delete'] || [];
    var up = req.upsert || null;
    var ensure = req.ensure || [];
    var store = $.EKEventStore.alloc.init;
    access(store);

    var probes = dels.slice();
    if (up && up.match) probes.push(up.match);
    ensure.forEach(function (e) { probes.push(e); });
    var events = null;
    if (probes.length) {
      var lo = Infinity, hi = -Infinity;
      probes.forEach(function (p) {
        lo = Math.min(lo, ms(p.start));
        hi = Math.max(hi, ms(p.end || p.start));
      });
      var pred = store.predicateForEventsWithStartDateEndDateCalendars(
        nsdate(lo - 6 * 3600e3), nsdate(hi + 6 * 3600e3), $());
      events = store.eventsMatchingPredicate(pred);
    }

    function hit(ev, p) {
      var title = ObjC.unwrap(ev.title) || '';
      if (title.indexOf(p.prefix) !== 0) return false;
      if (Math.abs(ev.startDate.timeIntervalSince1970 * 1000 - ms(p.start)) > 60e3) return false;
      if (p.end && Math.abs(ev.endDate.timeIntervalSince1970 * 1000 - ms(p.end)) > 60e3) return false;
      return true;
    }

    var deleted = 0, updated = 0, created = 0, errors = [];
    var moved = false;
    var present = ensure.map(function () { return false; });
    for (var i = 0; events && i < events.count; i++) {
      var ev = events.objectAtIndex(i);
      if (up && up.match && !moved && hit(ev, { prefix: up.prefix, start: up.match.start, end: up.match.end })) {
        ev.title = $(up.title);
        ev.startDate = nsdate(ms(up.start));
        ev.endDate = nsdate(ms(up.end));
        if (up.notes) ev.notes = $(up.notes);
        if (store.saveEventSpanCommitError(ev, $.EKSpanThisEvent, true, $())) { updated++; moved = true; }
        else errors.push('could not move the chat');
        continue;
      }
      var kept = false;
      for (var k = 0; k < ensure.length; k++) {
        if (!present[k] && hit(ev, ensure[k])) { present[k] = true; kept = true; break; }
      }
      if (kept) continue;
      for (var j = 0; j < dels.length; j++) {
        if (hit(ev, dels[j])) {
          if (store.removeEventSpanCommitError(ev, $.EKSpanThisEvent, true, $())) deleted++;
          else errors.push('could not delete an event');
          break;
        }
      }
    }

    function make(spec) {
      var cal = store.defaultCalendarForNewEvents;
      if (!cal || (cal.isNil && cal.isNil())) { errors.push('no default calendar'); return false; }
      var ne = $.EKEvent.eventWithEventStore(store);
      ne.calendar = cal;
      ne.title = $(spec.title);
      ne.startDate = nsdate(ms(spec.start));
      ne.endDate = nsdate(ms(spec.end));
      if (spec.notes) ne.notes = $(spec.notes);
      ne.availability = $.EKEventAvailabilityBusy;
      if (store.saveEventSpanCommitError(ne, $.EKSpanThisEvent, true, $())) return true;
      errors.push('could not create ' + spec.title);
      return false;
    }
    for (var e2 = 0; e2 < ensure.length; e2++) {
      if (!present[e2] && make(ensure[e2])) created++;
    }

    if (up && !moved) {
      var cal = store.defaultCalendarForNewEvents;
      if (!cal || cal.isNil && cal.isNil()) {
        errors.push('no default calendar');
      } else {
        var ne = $.EKEvent.eventWithEventStore(store);
        ne.calendar = cal;
        ne.title = $(up.title);
        ne.startDate = nsdate(ms(up.start));
        ne.endDate = nsdate(ms(up.end));
        if (up.notes) ne.notes = $(up.notes);
        if (store.saveEventSpanCommitError(ne, $.EKSpanThisEvent, true, $())) created++;
        else errors.push('could not create the chat event');
      }
    }
    return JSON.stringify({ ok: true, deleted: deleted, updated: updated, created: created, errors: errors });
  } catch (e) {
    return JSON.stringify({ ok: false, error: String(e.message || e) });
  }
}
