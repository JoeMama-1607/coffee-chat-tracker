#!/bin/bash
# Runs Coffee Chat Tracker in the foreground with its log on screen.
# Use this if the app icon does not seem to do anything — the reason will
# print here.

set -u
cd "$(dirname "$0")" || exit 1
SRC="$(pwd -P)"

HOME_REAL="$(cd "$HOME" && pwd -P)"
case "$SRC/" in
  "$HOME_REAL/Documents/"*|"$HOME_REAL/Desktop/"*|"$HOME_REAL/Downloads/"*|"$HOME_REAL/Library/Mobile Documents/"*|/Volumes/*)
    echo "This folder is inside Documents, Desktop, Downloads, iCloud Drive or an"
    echo "external drive. macOS blocks the app from reading files there."
    echo
    echo "Move the whole CoffeeChatTracker folder into your home folder (in Finder,"
    echo "Shift-Command-H opens it), then double-click install.command inside it."
    read -r -p "Press return to close." _
    exit 1 ;;
esac

PY=""
for c in "$SRC/runtime/python/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] || continue
  if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo "The app's copy of Python is missing."
  echo "Double-click install.command in this folder to set it up, then try again."
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
