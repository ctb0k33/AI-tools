#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
PROFILE_DIR="${PROFILE_DIR:-/app/profiles/x_profile}"
LOGIN_URL="${LOGIN_URL:-https://x.com/home}"
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1440x1000x24}"

mkdir -p "$PROFILE_DIR"

Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" >/tmp/xvfb.log 2>&1 &
fluxbox >/tmp/fluxbox.log 2>&1 &

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

python -m tools.daily_research.scripts.open_chrome_profile \
  --profile-dir "$PROFILE_DIR" \
  --chrome-path "$CHROME_PATH" \
  --start-url "$LOGIN_URL"

wait
