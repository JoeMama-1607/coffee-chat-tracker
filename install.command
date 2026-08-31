#!/bin/bash
# Builds "Coffee Chat Tracker.app" from this folder and puts it in ~/Applications.
# Safe to run again any time — it rebuilds the launcher in place.

set -u
cd "$(dirname "$0")" || exit 1
SRC="$(pwd)"
APPS="$HOME/Applications"
APP="$APPS/Coffee Chat Tracker.app"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }

echo
bold "Coffee Chat Tracker — install"
echo "  Source: $SRC"
echo

# ---------------------------------------------------------------- checks
bold "Checking this Mac"

PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$c" ] && [ -x "$c" ] || continue
  if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  bad "No usable Python 3.9+ found."
  echo
  echo "  Run this, accept the prompt, wait for it to finish, then run install.command again:"
  echo
  echo "      xcode-select --install"
  echo
  read -r -p "  Press return to close." _
  exit 1
fi
ok "Python: $PY ($("$PY" -c 'import platform;print(platform.python_version())'))"

if [ -d "/Applications/Microsoft Outlook.app" ]; then
  ok "Microsoft Outlook is installed"
else
  warn "Outlook not found in /Applications — mail tracking will be unavailable"
fi

if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  ok "Chrome found — the app will open in its own clean window"
else
  warn "Chrome not found — the app will open in your default browser instead"
fi

# ----------------------------------------------------------- build bundle
echo
bold "Building the app"

mkdir -p "$APPS"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$SRC/Info.plist" "$APP/Contents/Info.plist"
sed "s|__APP_DIR__|$SRC|g" "$SRC/launcher.sh" > "$APP/Contents/MacOS/CoffeeChatTracker"
chmod +x "$APP/Contents/MacOS/CoffeeChatTracker"
printf 'APPL????' > "$APP/Contents/PkgInfo"
ok "Bundle written to $APP"

# An ad-hoc signature gives the app a stable identity, so macOS remembers the
# calendar and automation permissions you grant it instead of asking every time.
if command -v codesign >/dev/null 2>&1; then
  if codesign --force --sign - "$APP" >/dev/null 2>&1; then
    ok "Signed ad-hoc (permissions will stick)"
  else
    warn "Could not sign — macOS may re-ask for permission after updates"
  fi
fi

chmod +x "$SRC/Run in Terminal.command" 2>/dev/null

echo
bold "Done"
echo "  Open it from ~/Applications, or run:  open \"$APP\""
echo
echo "  First launch will ask for two permissions:"
echo "    • Calendar  — to find times that do not clash"
echo "    • Outlook   — to open drafts and see who replied"
echo
read -r -p "  Press return to close, or type 'open' then return to launch now: " answer
if [ "$answer" = "open" ]; then open "$APP"; fi
