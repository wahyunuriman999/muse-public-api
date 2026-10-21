#!/usr/bin/env bash
# setup.sh — generate all local secrets and config for muse-public-api.
# Idempotent: existing secrets are never overwritten. Prints NO secret values.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p .secrets relay/queue relay/done relay/stale

gen_alnum() { python3 -c "import secrets, string, sys; n = int(sys.argv[1]); print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n)), end='')" "${1:-48}"; }

if [ ! -f .secrets/proxy-key ]; then
  printf 'mk-%s' "$(gen_alnum 40)" > .secrets/proxy-key
  echo "generated .secrets/proxy-key (client-facing API key)"
fi
if [ ! -f .secrets/relay-key ]; then
  printf 'rk-%s' "$(gen_alnum 40)" > .secrets/relay-key
  echo "generated .secrets/relay-key (internal bridge key)"
fi
if [ ! -f .secrets/poll-secret ]; then
  gen_alnum 48 > .secrets/poll-secret
  echo "generated .secrets/poll-secret (Worker <-> poller shared secret)"
fi
chmod 600 .secrets/*

if [ ! -f tunnel/config.env ]; then
  {
    echo "WORKER_URL="
    echo "POLL_SECRET=$(cat .secrets/poll-secret)"
  } > tunnel/config.env
  chmod 600 tunnel/config.env
  echo "wrote tunnel/config.env (WORKER_URL is filled in by deploy-worker.sh)"
fi

echo
echo "Setup done. Next steps:"
echo "  1. Create the answering-worker schedule (see WORKER_CRON.md)."
echo "  2. Deploy the Worker:  CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... bash scripts/deploy-worker.sh"
echo "  3. Start the stack:    bash scripts/start-all.sh"
echo "  4. Show your endpoint: bash scripts/show-connection.sh"
