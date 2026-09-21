#!/bin/bash
# Coffee Chat Tracker — installer.
#
# Double-click this file. It:
#   1. makes sure this folder is somewhere macOS lets the app read,
#   2. downloads a private copy of Python into this folder (nothing to install
#      yourself, and it never touches any Python already on your Mac),
#   3. builds "Coffee Chat Tracker.app" right here in this folder.
#
# Safe to run again: if everything is already set up it just says so.

set -u
answer=""
cd "$(dirname "$0")" || exit 1
SRC="$(pwd -P)"
APP="$SRC/Coffee Chat Tracker.app"
RUNTIME="$SRC/runtime"
PY_BUNDLED="$RUNTIME/python/bin/python3"

# The private Python. Builds from python-build-standalone (the same builds uv
# uses), pinned by version and verified by SHA-256 before anything is used.
PY_VERSION="3.12.14"
PY_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/20260901"
PY_ARM_URL="$PY_BASE/cpython-3.12.14%2B20260901-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_ARM_SHA="81a359f1cfadd4da11766534c5913791cea55f26e1bb902cacd2a531bb1e4b2b"
PY_X86_URL="$PY_BASE/cpython-3.12.14%2B20260901-x86_64-apple-darwin-install_only_stripped.tar.gz"
PY_X86_SHA="65b195c9cedc1fef6767f044f9822069adbd1bd9204d424ece4628776fdc04bb"

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
say()  { printf '  %s\n' "$1"; }

finish() {
  echo
  read -r -p "  Press return to close this window. " _
  exit "${1:-0}"
}

echo
printf '\033[1m☕  Coffee Chat Tracker — setup\033[0m\n'
say "Folder: $SRC"

# ------------------------------------------------------------------ 1. place
# macOS quietly refuses to let a background program like this app's Python
# read anything inside Documents, Desktop, Downloads, iCloud Drive or an
# external drive. There is no permission prompt — the app just fails to start.
# So stop here, before building something that cannot work.

HOME_REAL="$(cd "$HOME" && pwd -P)"
PROTECTED=""
case "$SRC/" in
  "$HOME_REAL/Documents/"*)              PROTECTED="Documents" ;;
  "$HOME_REAL/Desktop/"*)                PROTECTED="Desktop" ;;
  "$HOME_REAL/Downloads/"*)              PROTECTED="Downloads" ;;
  "$HOME_REAL/Library/Mobile Documents/"*) PROTECTED="iCloud Drive" ;;
  /Volumes/*)                            PROTECTED="an external or network drive" ;;
esac

if [ -n "$PROTECTED" ]; then
  TARGET="$HOME_REAL/CoffeeChatTracker"
  bold "One quick move first"
  say "This folder is inside $PROTECTED. macOS blocks apps from reading"
  say "files there, so Coffee Chat Tracker would not start."
  echo
  say "It needs to live in your home folder instead:"
  say "    $TARGET"

  if [ -e "$TARGET" ]; then
    echo
    warn "There is already a CoffeeChatTracker folder in your home folder."
    say "If that is an older copy of this app, drag it to the Trash"
    say "(your saved people and notes are stored elsewhere and are safe),"
    say "then double-click this install.command again."
    finish 1
  fi

  echo
  say "I can move it for you. Or do it yourself: in Finder press"
  say "Shift-Command-H to open your home folder and drag this folder there."
  echo
  read -r -p "  Type  move  and press return to move it now (or just press return to close): " answer
  if [ "$answer" = "move" ]; then
    if mv "$SRC" "$TARGET" 2>/dev/null; then
      ok "Moved to $TARGET"
      open "$TARGET" >/dev/null 2>&1
      say "Carrying on with setup from the new location…"
      exec /bin/bash "$TARGET/install.command"
    fi
    bad "macOS would not let me move it."
    say "Please drag the folder into your home folder in Finder"
    say "(Shift-Command-H opens it), or paste this into Terminal:"
    echo
    printf '      mv "%s" ~/\n' "$SRC"
    echo
    say "Then double-click install.command inside the moved folder."
  fi
  finish 1
fi
ok "Folder location is fine"

# ----------------------------------------------------------- 2. Python
runtime_version() {
  [ -x "$PY_BUNDLED" ] || return 1
  "$PY_BUNDLED" -c 'import sqlite3, zoneinfo, platform; print(platform.python_version())' 2>/dev/null
}

# Anything that fails to run straight after download gets an ad-hoc signature,
# which Apple Silicon requires of every binary it executes. codesign ships
# with macOS itself.
sign_tree() {
  command -v codesign >/dev/null 2>&1 || return 0
  find "$1" -type f \( -name 'python3*' -o -name '*.dylib' -o -name '*.so' \) -print0 2>/dev/null \
    | xargs -0 codesign --force --sign - >/dev/null 2>&1
}

install_runtime() {
  local url sha tmp sum
  if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    url="$PY_ARM_URL"; sha="$PY_ARM_SHA"
  else
    url="$PY_X86_URL"; sha="$PY_X86_SHA"
  fi
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/coffeechat.XXXXXX")" || return 1

  if ! curl -fL --retry 3 --connect-timeout 20 --progress-bar -o "$tmp/python.tar.gz" "$url"; then
    rm -rf "$tmp"; return 1
  fi
  sum="$(shasum -a 256 "$tmp/python.tar.gz" | awk '{print $1}')"
  if [ "$sum" != "$sha" ]; then
    bad "The download did not match its checksum, so it was thrown away."
    rm -rf "$tmp"; return 1
  fi

  mkdir -p "$tmp/unpacked" && tar -xzf "$tmp/python.tar.gz" -C "$tmp/unpacked" || { rm -rf "$tmp"; return 1; }
  if ! "$tmp/unpacked/python/bin/python3" -c 'import sqlite3, zoneinfo' >/dev/null 2>&1; then
    sign_tree "$tmp/unpacked/python"
    "$tmp/unpacked/python/bin/python3" -c 'import sqlite3, zoneinfo' >/dev/null 2>&1 || { rm -rf "$tmp"; return 1; }
  fi

  # Swap in only once the new copy is known to work.
  rm -rf "$RUNTIME"
  mkdir -p "$RUNTIME" && mv "$tmp/unpacked/python" "$RUNTIME/python"
  rm -rf "$tmp"
  [ "$(runtime_version)" = "$PY_VERSION" ]
}

ensure_python() {
  local current
  current="$(runtime_version || true)"
  if [ "$current" = "$PY_VERSION" ]; then
    ok "Python $current (private copy, up to date)"
    return 0
  fi
  if [ -n "$current" ]; then
    say "Updating the app's Python from $current to $PY_VERSION…"
  else
    bold "Getting Python"
    say "Downloading the app's own copy of Python (about 25 MB, one time only)."
    say "This does not change anything else on your Mac."
  fi
  if install_runtime; then
    ok "Python $PY_VERSION ready"
    return 0
  fi
  return 1
}

system_python() {
  local c
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$c" ] || continue
    if "$c" -c 'import sys, sqlite3, zoneinfo; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      echo "$c"; return 0
    fi
  done
  return 1
}

if ! ensure_python; then
  warn "Could not download Python — usually a Wi-Fi hiccup."
  if FALLBACK="$(system_python)"; then
    ok "Using the Python already on this Mac instead ($FALLBACK)"
    say "Next time you have a good connection, run install.command again"
    say "and it will fetch its own copy."
  else
    # Last resort: Apple's own Command Line Tools, which include Python. This
    # pops up Apple's installer; it cannot be made silent or made to wait.
    bold "One extra step"
    say "Please check your internet connection. If it is fine, Apple's own"
    say "installer is opening now — it provides the Python this app needs."
    echo
    xcode-select --install >/dev/null 2>&1 || true
    say "1. In the window that appears, click  Install  and agree."
    say "2. Wait for it to finish (a few minutes)."
    say "3. Double-click install.command again."
    finish 1
  fi
fi

# --------------------------------------------------- 3. already installed?
if [ -x "$APP/Contents/MacOS/CoffeeChatTracker" ]; then
  bold "Already installed"
  ok "Coffee Chat Tracker is set up in this folder:"
  say "    $APP"
  echo
  say "Open it from your CoffeeChatTracker folder, or search for it in Spotlight."
  say "If it ever seems not to open, double-click  Run in Terminal.command"
  say "in the same folder — it shows what is going wrong."
  echo
  read -r -p "  Press return to close, type  open  to launch it, or  reinstall  to rebuild: " answer
  case "$answer" in
    open) open "$APP"; exit 0 ;;
    reinstall) say "Rebuilding…" ;;
    *) exit 0 ;;
  esac
fi

# --------------------------------------------------------- 4. build
bold "Building the app"

# Files that arrived by download carry a quarantine flag, which makes macOS
# ask about each one separately. You have already approved this installer, so
# clear it for the rest of the folder.
xattr -dr com.apple.quarantine "$SRC" 2>/dev/null || true

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SRC/Info.plist" "$APP/Contents/Info.plist"
sed "s|__APP_DIR__|$SRC|g" "$SRC/launcher.sh" > "$APP/Contents/MacOS/CoffeeChatTracker"
chmod +x "$APP/Contents/MacOS/CoffeeChatTracker"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# An ad-hoc signature gives the app a stable identity, so macOS remembers the
# Calendar permission you grant it instead of asking every time.
if command -v codesign >/dev/null 2>&1 && codesign --force --sign - "$APP" >/dev/null 2>&1; then
  ok "App built and signed"
else
  ok "App built"
fi

# Let Spotlight and Finder know it exists straight away.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$APP" >/dev/null 2>&1
command -v mdimport >/dev/null 2>&1 && mdimport "$APP" >/dev/null 2>&1

chmod +x "$SRC/Run in Terminal.command" "$SRC/install.command" 2>/dev/null

if [ -d "/Applications/Microsoft Outlook.app" ]; then
  ok "Microsoft Outlook found"
else
  warn "Outlook not found — everything works except drafting and mail tracking"
fi

OLD="$HOME_REAL/Applications/Coffee Chat Tracker.app"
if [ -d "$OLD" ]; then
  warn "An older copy is in ~/Applications. You can drag that one to the Trash —"
  say "  the app now lives in this folder."
fi

# ---------------------------------------------------------------- done
bold "All set ☕"
say "Open it from your CoffeeChatTracker folder, or search for it in Spotlight."
echo
say "The first time it opens, macOS will ask to let it use your Calendar"
say "(and Outlook). That is expected — click Allow / OK."
echo
read -r -p "  Press return to close, or type  open  then return to launch it now: " answer
[ "$answer" = "open" ] && open "$APP"
exit 0
