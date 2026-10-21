#!/usr/bin/env bash
# deploy-worker.sh — deploy the muse-tunnel Cloudflare Worker with wrangler.
#
# Requires a Cloudflare API token with the "Edit Cloudflare Workers" template
# permissions and the account ID, supplied via environment (never commit them):
#   CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... bash scripts/deploy-worker.sh
#
# The Worker source contains a __INTERNAL_SECRET__ placeholder; the real
# poll secret from tunnel/config.env is substituted into a gitignored
# .build/ copy at deploy time. The committed source never contains a secret.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN (one-time deploy token)}"
: "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID}"
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

POLL_SECRET="$(grep '^POLL_SECRET=' tunnel/config.env | cut -d= -f2-)"
[ -n "$POLL_SECRET" ] || { echo "POLL_SECRET missing — run scripts/setup.sh first"; exit 1; }

mkdir -p .build
sed "s/__INTERNAL_SECRET__/$POLL_SECRET/" tunnel/muse-tunnel-worker.js > .build/worker.js
cat > .build/wrangler.toml <<'EOF'
name = "muse-tunnel"
main = "worker.js"
compatibility_date = "2025-01-01"

[[durable_objects.bindings]]
name = "RELAY"
class_name = "Relay"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["Relay"]
EOF

CI=true WRANGLER_SEND_METRICS=false npx -y wrangler@latest deploy -c .build/wrangler.toml 2>&1 | tee .build/deploy.log
URL="$(grep -oE 'https://[A-Za-z0-9.-]+\.workers\.dev' .build/deploy.log | head -1)"
[ -n "$URL" ] || { echo "could not parse workers.dev URL from wrangler output — see .build/deploy.log"; exit 1; }

sed -i "s|^WORKER_URL=.*|WORKER_URL=$URL|" tunnel/config.env
echo
echo "Worker deployed: $URL"
echo "WORKER_URL written to tunnel/config.env"
echo "IMPORTANT: delete the one-time deploy token now (Cloudflare dashboard -> My Profile -> API Tokens)."
echo "It cannot revoke itself via the API (the Workers template has no token-management permission)."
echo "Next: bash scripts/start-all.sh && bash scripts/show-connection.sh"
