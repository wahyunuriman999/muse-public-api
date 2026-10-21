#!/usr/bin/env bash
# start-all.sh — start bridge + proxy + poller, then probe local health.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

bash "$ROOT/relay/start-bridge.sh"
bash "$ROOT/proxy/start.sh"
bash "$ROOT/tunnel/start-poller.sh"
sleep 3

echo "--- local health ---"
curl -s -m 5 http://127.0.0.1:20129/health && echo "  <- relay bridge :20129"
curl -s -m 5 http://127.0.0.1:20130/health && echo "  <- llm-proxy :20130"
tail -2 "$ROOT/tunnel/poller.log" 2>/dev/null || true
