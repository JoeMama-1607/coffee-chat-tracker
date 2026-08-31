#!/bin/bash
# Coffee Chat Tracker launcher.
#
# Finds a usable python3, starts the local app server, opens the interface in a
# clean app window, and stays alive until you close that window.

set -u

APP_DIR="__APP_DIR__"
LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/CoffeeChatTracker.log"
mkdir -p "$LOG_DIR"

say_error() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Coffee Chat Tracker\" with icon caution" >/dev/null 2>&1
}

if [ ! -f "$APP_DIR/app/server.py" ]; then
  say_error "Coffee Chat Tracker cannot find its files.\n\nExpected them at:\n$APP_DIR\n\nIf you moved the CoffeeChatTracker folder, run install.command inside it again."
  exit 1
fi

find_python() {
  local candidates=(
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    /usr/bin/python3
    "$(command -v python3 2>/dev/null || true)"
  )
  for c in "${candidates[@]}"; do
    [ -n "$c" ] || continue
    [ -x "$c" ] || continue
    if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  say_error "Coffee Chat Tracker needs Python 3.9 or newer, which is not installed yet.\n\nOpen Terminal and run:\n\n    xcode-select --install\n\nAccept the prompt, wait for it to finish, then launch the app again."
  exit 1
}

echo "--- $(date) starting with $PY" >>"$LOG"

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
  say_error "The app server did not start.\n\nDetails were written to:\n$LOG"
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
