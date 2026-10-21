#!/usr/bin/env bash
# test-public.sh — end-to-end test against the PUBLIC workers.dev endpoint.
#   bash scripts/test-public.sh          # /v1/models (fast)
#   bash scripts/test-public.sh --chat   # + a real chat completion (can take minutes)
# NOTE: never probe /internal/jobs manually while testing — that endpoint
# claims queued jobs for whoever calls it and will steal them from the poller.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKER_URL="$(grep '^WORKER_URL=' "$ROOT/tunnel/config.env" | cut -d= -f2-)"
KEY="$(cat "$ROOT/.secrets/proxy-key")"

echo "== GET $WORKER_URL/v1/models =="
curl -s -m 60 -w "\nHTTP %{http_code}\n" "$WORKER_URL/v1/models" -H "Authorization: Bearer $KEY"

if [ "${1:-}" = "--chat" ]; then
  echo "== POST $WORKER_URL/v1/chat/completions (long-poll, up to 660s) =="
  curl -s -m 660 -w "\nHTTP %{http_code}\n" "$WORKER_URL/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d '{"model":"muse","messages":[{"role":"user","content":"Connection test: reply with exactly PING-OK."}]}'
fi
