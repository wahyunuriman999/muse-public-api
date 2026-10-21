#!/usr/bin/env bash
# Start llm-proxy in the background. Reads keys from ../.secrets/, never prints them.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
export PROXY_API_KEY="$(cat "$ROOT/.secrets/proxy-key")"
export RELAY_KEY="$(cat "$ROOT/.secrets/relay-key")"
export PROXY_PORT="${PROXY_PORT:-20130}"
# avoid duplicates (full path — a short pattern also matches other installs)
if pgrep -f "$DIR/proxy[.]py" >/dev/null 2>&1; then
  echo "llm-proxy already running"
  exit 0
fi
# setsid detaches the proxy into its own session so a killed launcher/cron
# session can't SIGTERM it along with the process tree; disown stops this
# script's bash from waiting on the background job at exit.
setsid nohup python3 "$DIR/proxy.py" < /dev/null >> "$DIR/proxy.log" 2>&1 &
disown
echo "llm-proxy started, pid $!"
