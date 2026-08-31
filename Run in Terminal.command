#!/bin/bash
# Runs Coffee Chat Tracker in the foreground with its log on screen.
# Use this if the app icon does not seem to do anything — the reason will
# print here.

set -u
cd "$(dirname "$0")" || exit 1

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$c" ] && [ -x "$c" ] || continue
  if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo "No usable Python 3.9+ found. Run:  xcode-select --install"
  read -r -p "Press return to close." _
  exit 1
fi

echo "Starting Coffee Chat Tracker with $PY"
echo "Leave this window open while you use the app. Ctrl-C to stop."
echo

"$PY" app/server.py --no-watchdog | while IFS= read -r line; do
  echo "$line"
  case "$line" in
    CCT_URL=*)
      URL="${line#CCT_URL=}"
      CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      if [ -x "$CHROME" ]; then
        "$CHROME" --app="$URL" --window-size=1360,900 >/dev/null 2>&1 &
      else
        open "$URL"
      fi
      ;;
  esac
done
