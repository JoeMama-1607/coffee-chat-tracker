// Reads the text of a LinkedIn profile tab you already have open, in Safari
// or Chrome. Prints JSON: {ok:true, url, browser, text} or {ok:false, error}.
//
// Run:  osascript -l JavaScript browser_read.js
//
// This does not log in, search, or open anything — it reads one tab you are
// already looking at, in your own already-authenticated session. Safari and
// Chrome both refuse to run JavaScript from Apple Events until you turn that
// on by hand (Safari: Develop menu > Allow JavaScript from Apple Events.
// Chrome: View > Developer > Allow JavaScript from Apple Events), which is
// why that is the first thing this script's errors point at.

ObjC.import('Foundation');

var PROFILE_URL = /^https?:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\//i;

var EXTRACT_JS =
  "(function(){" +
  "var el = document.querySelector('main') || " +
  "document.querySelector('.scaffold-layout__main') || document.body;" +
  "return el ? el.innerText : '';" +
  "})();";

function isRunning(name) {
  try {
    return Application(name).running();
  } catch (e) {
    return false;
  }
}

function safariTabs() {
  var out = [];
  var app = Application('Safari');
  var windows = app.windows();
  for (var w = 0; w < windows.length; w++) {
    var tabs;
    try { tabs = windows[w].tabs(); } catch (e) { continue; }
    for (var t = 0; t < tabs.length; t++) {
      var url = '';
      try { url = tabs[t].url(); } catch (e) {}
      out.push({ url: url, front: w === 0 && t === windows[w].currentTab.index() - 1, tab: tabs[t] });
    }
  }
  return { app: app, tabs: out };
}

function chromeTabs() {
  var out = [];
  var app = Application('Google Chrome');
  var windows = app.windows();
  for (var w = 0; w < windows.length; w++) {
    var tabs;
    try { tabs = windows[w].tabs(); } catch (e) { continue; }
    var activeIndex = -1;
    try { activeIndex = windows[w].activeTabIndex(); } catch (e) {}
    for (var t = 0; t < tabs.length; t++) {
      var url = '';
      try { url = tabs[t].url(); } catch (e) {}
      out.push({ url: url, front: w === 0 && (t + 1) === activeIndex, tab: tabs[t] });
    }
  }
  return { app: app, tabs: out };
}

function pickTab(bundle) {
  var candidates = bundle.tabs.filter(function (t) { return PROFILE_URL.test(t.url); });
  if (!candidates.length) return null;
  var front = candidates.filter(function (t) { return t.front; });
  return front.length ? front[0] : candidates[0];
}

function readSafari() {
  if (!isRunning('Safari')) return { found: false };
  var bundle = safariTabs();
  var match = pickTab(bundle);
  if (!match) return { found: false };
  try {
    var text = bundle.app.doJavaScript(EXTRACT_JS, { in: match.tab });
    return { found: true, ok: true, url: match.url, browser: 'Safari', text: text };
  } catch (e) {
    return {
      found: true, ok: false, url: match.url, browser: 'Safari',
      error: 'Safari would not run JavaScript for this (' + e.message + '). Turn on ' +
        'Safari > Settings > Advanced > "Show features for web developers", then ' +
        'Develop > Allow JavaScript from Apple Events.',
    };
  }
}

function readChrome() {
  if (!isRunning('Google Chrome')) return { found: false };
  var bundle = chromeTabs();
  var match = pickTab(bundle);
  if (!match) return { found: false };
  try {
    var text = bundle.app.execute(match.tab, { javascript: EXTRACT_JS });
    return { found: true, ok: true, url: match.url, browser: 'Chrome', text: text };
  } catch (e) {
    return {
      found: true, ok: false, url: match.url, browser: 'Chrome',
      error: 'Chrome would not run JavaScript for this (' + e.message + '). Turn on ' +
        'Chrome > View > Developer > Allow JavaScript from Apple Events.',
    };
  }
}

function run() {
  var attempts = [readSafari(), readChrome()];
  var hit = attempts.filter(function (a) { return a.found; });

  if (!hit.length) {
    return JSON.stringify({
      ok: false,
      error: 'No open LinkedIn profile tab found in Safari or Chrome. Open the ' +
        'profile (a URL like linkedin.com/in/…), make it the front tab, and try again.',
    });
  }

  var success = hit.filter(function (a) { return a.ok; });
  if (success.length) {
    var best = success[0];
    return JSON.stringify({ ok: true, url: best.url, browser: best.browser, text: best.text });
  }

  return JSON.stringify({ ok: false, error: hit[0].error });
}
