#!/usr/bin/env bash
# Start the muse-relay bridge in the background (detached daemon).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/queue" "$DIR/done" "$DIR/stale"
if [ -f "$DIR/bridge.pid" ] && kill -0 "$(cat "$DIR/bridge.pid")" 2>/dev/null; then
  echo "muse-relay bridge already running (pid $(cat "$DIR/bridge.pid"))"
  exit 0
fi
# setsid + disown: the daemon must survive the launcher session being killed
# (see README "Operational notes").
setsid nohup python3 "$DIR/bridge.py" < /dev/null >> "$DIR/bridge.log" 2>&1 &
disown
echo "muse-relay bridge started, pid $!"
