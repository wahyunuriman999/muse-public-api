#!/usr/bin/env bash
# Start ws-poller daemon. Reads config from config.env next to poller.py.
# Run unpiped; leave the launcher session alone (daemon survival notes in README).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$DIR/config.env" ]; then
  echo "missing $DIR/config.env (run scripts/setup.sh first, then scripts/deploy-worker.sh)"
  exit 1
fi
if pgrep -f "$DIR/poller[.]py" >/dev/null 2>&1; then
  echo "ws-poller already running"
  exit 0
fi
setsid nohup python3 "$DIR/poller.py" < /dev/null >> "$DIR/poller.log" 2>&1 &
disown
echo "ws-poller started, pid $!"
