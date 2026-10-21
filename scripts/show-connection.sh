#!/usr/bin/env bash
# show-connection.sh — print the finished endpoint for the owner.
# This is the intended final output of the whole setup: base URL + API key.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WORKER_URL="$(grep '^WORKER_URL=' "$ROOT/tunnel/config.env" 2>/dev/null | cut -d= -f2- || true)"
[ -n "${WORKER_URL:-}" ] || { echo "WORKER_URL is empty — run scripts/deploy-worker.sh first."; exit 1; }
[ -f "$ROOT/.secrets/proxy-key" ] || { echo "missing .secrets/proxy-key — run scripts/setup.sh first."; exit 1; }

echo "Your Muse API is live:"
echo
echo "  Base URL : $WORKER_URL/v1"
echo "  API Key  : $(cat "$ROOT/.secrets/proxy-key")"
echo "  Model    : muse"
echo
echo "Connect any OpenAI-compatible tool with those three values."
echo "Client timeout must be >= 660s; treat responses as non-streaming (see README)."
