# SETUP_FOR_MUSE.md — agent brief

You are a Muse agent. Your user wants this repository set up end-to-end so
their Muse (you) becomes reachable through a public OpenAI-compatible API.
Execute the phases in order. Do not skip verification. Report status as
VERIFIED / PARTIALLY VERIFIED / BLOCKED with evidence, never as vibes.

**Final deliverable — the user must receive exactly this at the end:**

```
Base URL : https://<worker>.workers.dev/v1
API Key  : <contents of .secrets/proxy-key>
Model    : muse
```

(`bash scripts/show-connection.sh` prints it.)

## Phase 0 — prerequisites

- `python3`, `node` + `npx`, `curl` available on your VM.
- A clone of this repo on your VM (paths below assume the clone root is the
  working directory).
- The user has a Cloudflare account (free plan is enough).

## Phase 1 — local stack

```bash
bash scripts/setup.sh        # generates secrets; idempotent
bash relay/start-bridge.sh
bash proxy/start.sh
curl http://127.0.0.1:20129/health   # {"ok": true}
curl http://127.0.0.1:20130/health   # {"status":"ok"}
KEY=$(cat .secrets/proxy-key)
curl http://127.0.0.1:20130/v1/models -H "Authorization: Bearer $KEY"   # lists "muse"
```

Gate: all four checks pass before continuing.

## Phase 2 — the answering worker (do not skip)

Create the recurring agent schedule described in `WORKER_CRON.md` (every
2 minutes, body verbatim with your clone path). Without it, chat requests
queue forever and every public chat test times out at 600s. Also create the
janitor schedule if your runtime supports it.

## Phase 3 — Cloudflare sign-in + one-time token (user gate)

The user signs in **personally** — never enter their credentials, never ask
for a password in chat.

1. Open the Cloudflare dashboard in the browser; the user takes over,
   signs in (including any human-verification/2FA), and hands control back.
2. In that session: Workers & Pages → create a Worker named `muse-tunnel`
   (placeholder deploy is fine — wrangler will overwrite it). This also
   registers the account's `workers.dev` subdomain if it is the first Worker.
3. In that session: My Profile → API Tokens → Create Token → template
   **Edit Cloudflare Workers**, name it `muse-tunnel-deploy`, default
   scopes → create. Note the token value and the Account ID (dashboard URL).
   Hand both to your shell **via environment variables only** — do not print
   the token in chat, files, commits, or logs.

## Phase 4 — deploy

```bash
CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... bash scripts/deploy-worker.sh
```

Gate: output shows the Worker uploaded with binding `env.RELAY (Relay)`,
a `https://muse-tunnel.<subdomain>.workers.dev` URL, and `WORKER_URL`
written into `tunnel/config.env`.

## Phase 5 — delete the deploy token

The token cannot revoke itself via the API (no token-management permission
— DELETE returns 9109). Delete `muse-tunnel-deploy` in the dashboard
(Profile → API Tokens) in the same signed-in session and confirm it is gone
from the list. The Worker and poller do not use this token.

## Phase 6 — poller + public end-to-end

```bash
bash tunnel/start-poller.sh
bash scripts/test-public.sh          # expect HTTP 200, model list
bash scripts/test-public.sh --chat   # expect HTTP 200, content "PING-OK"
```

Gate: both pass from the public URL. Then run `bash scripts/show-connection.sh`
and deliver its output to the user (Phase "Final deliverable" above), plus a
one-line note on latency/timeout (≥ 660s, non-streaming).

## Troubleshooting — all of these were hit in production

- **Poller logs `poll: 403` with body `error code: 1010`** → Cloudflare is
  blocking the client's User-Agent. The shipped poller sends a browser UA;
  if you rewrote it, restore that header.
- **Public chat hangs, but manual `/internal/jobs` calls show jobs** → your
  manual calls *claimed* (stole) the jobs. Never probe that endpoint during
  tests; it claims for any caller. Re-run the test with zero manual probes.
- **`cloudflared` / named tunnels fail from the VM** → expected; this VM's
  network refuses them. That is why this repo uses the pull design.
- **Dashboard code editor paste fails / Monaco rejects automation** →
  expected; never use the dashboard editor. Wrangler is the deploy path.
- **Occasional `Remote end closed connection` poll errors** → egress-proxy
  flakiness (≈1 in 5). The poller retries every 10s; only act if errors are
  continuous for several minutes.
- **Port already in use on :20129/:20130** → an instance is already
  running; check before starting duplicates.

## Hard rules

- Never commit or print the deploy token, poll secret, relay key, or proxy
  key — except the proxy key once, to the user, as the final deliverable.
- Never paste the Worker code into the dashboard editor as a fallback.
- Change nothing else in the user's Cloudflare account (no DNS, zones,
  other tokens, plans, or billing).
