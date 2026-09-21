#!/bin/bash
# Coffee Chat Tracker launcher — the program inside "Coffee Chat Tracker.app".
#
# Starts the local app server with the app's own Python, opens the interface
# in a clean window, and stays alive until you close that window.

set -u

# The app lives inside the CoffeeChatTracker folder, so the folder is simply
# three levels up from here. Working it out at launch, rather than trusting
# the path recorded at install time, means moving the whole folder still works.
HERE="$(cd "$(dirname "$0")" && pwd -P)"
APP_DIR="$(cd "$HERE/../../.." && pwd -P)"
if [ ! -f "$APP_DIR/app/server.py" ]; then
  APP_DIR="__APP_DIR__"
fi

LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/CoffeeChatTracker.log"
mkdir -p "$LOG_DIR"

say_error() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Coffee Chat Tracker\" with icon caution" >/dev/null 2>&1
}

if [ ! -f "$APP_DIR/app/server.py" ]; then
  say_error "Coffee Chat Tracker cannot find its files.\n\nKeep the app inside its CoffeeChatTracker folder, and run install.command in that folder again."
  exit 1
fi

# macOS blocks the app from reading these locations without ever asking, so
# the app would silently fail to start. Say so plainly instead.
HOME_REAL="$(cd "$HOME" && pwd -P)"
case "$APP_DIR/" in
  "$HOME_REAL/Documents/"*|"$HOME_REAL/Desktop/"*|"$HOME_REAL/Downloads/"*|"$HOME_REAL/Library/Mobile Documents/"*|/Volumes/*)
    say_error "The CoffeeChatTracker folder is somewhere macOS won't let the app read (Documents, Desktop, Downloads, iCloud Drive or an external drive).\n\nMove the whole folder into your home folder — in Finder, Shift-Command-H opens it — then double-click install.command inside it."
    exit 1 ;;
esac

find_python() {
  local c
  for c in "$APP_DIR/runtime/python/bin/python3" \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$c" ] || continue
    if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  say_error "Coffee Chat Tracker is missing its copy of Python.\n\nDouble-click install.command in the CoffeeChatTracker folder to fetch it, then open the app again."
  exit 1
}

echo "--- $(date) starting with $PY in $APP_DIR" >>"$LOG"

OUT="$(mktemp -t coffeechat)"
"$PY" "$APP_DIR/app/server.py" >"$OUT" 2>>"$LOG" &
SERVER_PID=$!

URL=""
for _ in $(seq 1 120); do
  URL="$(/usr/bin/sed -n 's/^CCT_URL=//p' "$OUT" | head -1)"
  [ -n "$URL" ] && break
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  sleep 0.1
done

if [ -z "$URL" ]; then
  say_error "The app did not start.\n\nFor the reason, double-click Run in Terminal.command in the CoffeeChatTracker folder. Details were also written to:\n$LOG"
  rm -f "$OUT"
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ]; then
  # A Chrome app window: no tabs, no address bar, its own Dock icon.
  "$CHROME" --app="$URL" --window-size=1360,900 >/dev/null 2>&1 &
else
  /usr/bin/open "$URL"
fi

rm -f "$OUT"
wait "$SERVER_PID"
echo "--- $(date) stopped" >>"$LOG"
