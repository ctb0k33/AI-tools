#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
PROFILE_DIR="${PROFILE_DIR:-/app/profiles/x_profile}"
LOGIN_URL="${LOGIN_URL:-https://x.com/home}"
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1440x1000x24}"

mkdir -p "$PROFILE_DIR"
LOGIN_MARKER="$PROFILE_DIR/.x-login-active"
CHROME_LOG_PATH="${CHROME_LOG_PATH:-/tmp/chrome.log}"

cleanup() {
  rm -f "$LOGIN_MARKER"
}
trap cleanup EXIT INT TERM

remove_stale_profile_locks() {
  local lock_path="$PROFILE_DIR/SingletonLock"
  if [[ ! -e "$lock_path" && ! -L "$lock_path" ]]; then
    return 0
  fi

  local target=""
  target="$(readlink "$lock_path" 2>/dev/null || true)"
  local current_host=""
  current_host="$(hostname)"
  local is_active_here=0

  if [[ "$target" == "$current_host"-* ]]; then
    local pid="${target##*-}"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      is_active_here=1
    fi
  fi

  if [[ "$is_active_here" == "0" ]]; then
    echo "Removing stale Chromium profile locks for login profile: ${target:-unknown}"
    rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket"
  fi
}

remove_stale_profile_locks

{
  echo "hostname=$(hostname)"
  echo "pid=$$"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$LOGIN_MARKER"

Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" >/tmp/xvfb.log 2>&1 &
fluxbox >/tmp/fluxbox.log 2>&1 &
sleep "${LOGIN_STARTUP_DELAY_SECONDS:-2}"

if [[ -n "${VNC_PASSWORD:-}" ]]; then
  mkdir -p "$HOME/.vnc"
  x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null
  x11vnc -display "$DISPLAY" -forever -shared -rfbauth "$HOME/.vnc/passwd" -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
else
  x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
fi

websockify --web=/usr/share/novnc/ 7900 localhost:5900 >/tmp/novnc.log 2>&1 &

if [[ -z "${CHROME_PATH:-}" ]]; then
  CHROME_PATH="$(find /ms-playwright -path '*/chrome-linux/chrome' -type f | head -n 1)"
fi
if [[ -z "$CHROME_PATH" ]]; then
  echo "Could not find Playwright Chromium executable." >&2
  exit 1
fi

echo "Open http://localhost:7900/vnc.html in your host browser."
echo "Use the browser inside noVNC to sign in to X. Profile: $PROFILE_DIR"

export CHROME_LOG_PATH
export CHROME_DISABLE_GPU="${CHROME_DISABLE_GPU:-1}"

python -m tools.daily_research.scripts.open_chrome_profile \
  --profile-dir "$PROFILE_DIR" \
  --chrome-path "$CHROME_PATH" \
  --start-url "$LOGIN_URL" \
  --startup-wait-seconds "${CHROME_STARTUP_WAIT_SECONDS:-8}"

wait
