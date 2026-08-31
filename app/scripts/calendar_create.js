// Creates a single event in Apple Calendar. Only ever runs when you click
// "Add to Apple Calendar" on a confirmed chat — nothing is written automatically.
//
// Run: osascript -l JavaScript calendar_create.js <title> <startISO> <endISO> <notes> <calendarName>

ObjC.import('Foundation');

function run(argv) {
  var title = argv[0] || 'Coffee chat';
  var startISO = argv[1];
  var endISO = argv[2];
  var notes = argv[3] || '';
  var calendarName = argv[4] || '';

  if (!startISO || !endISO) {
    return JSON.stringify({ ok: false, error: 'start and end are required' });
  }

  try {
    var Calendar = Application('Calendar');
    var target = null;
    var calendars = Calendar.calendars();

    if (calendarName) {
      for (var i = 0; i < calendars.length; i++) {
        if (calendars[i].name() === calendarName) { target = calendars[i]; break; }
      }
    }
    if (!target) {
      // Prefer the calendar Calendar.app itself treats as default when writable.
      for (var j = 0; j < calendars.length; j++) {
        try {
          if (calendars[j].writable()) { target = calendars[j]; break; }
        } catch (e) { /* older versions lack `writable` */ }
      }
    }
    if (!target && calendars.length) target = calendars[0];
    if (!target) return JSON.stringify({ ok: false, error: 'no calendar available' });

    var event = Calendar.Event({
      summary: title,
      startDate: new Date(startISO),
      endDate: new Date(endISO),
      description: notes
    });
    target.events.push(event);
    Calendar.activate();

    return JSON.stringify({ ok: true, calendar: target.name() });
  } catch (e) {
    return JSON.stringify({ ok: false, error: String(e.message || e) });
  }
}
