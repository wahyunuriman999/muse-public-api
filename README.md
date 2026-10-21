# muse-public-api

Give your Muse a **public, OpenAI-compatible API endpoint** — a base URL +
API key that any of your tools can call, answered by Muse itself (the agent,
with its memory and tools), not by a raw model API.

```
your tools ──HTTPS──▶ Cloudflare Worker ──(job queue in a Durable Object)──┐
   ▲                                                                       │ poll every 10s
   │                        ┌──────────────────────────────────────────────┘
   └──── answer ────────────┤  poller ──▶ llm-proxy ──▶ muse-relay bridge
                                                      │ writes job file
                                                      ▼
                                              relay/queue/*.json
                                                      │ answered by a
                                                      ▼ scheduled Muse job
                                                   Muse itself
```

## Why it looks like this

A Muse VM has **no public IP and accepts no inbound connections**, and
outbound tunnel tools (cloudflared, localtunnel) do not survive its network.
So the direction is inverted: the Cloudflare Worker receives public requests
and stores them as jobs; the VM *polls outward* for jobs, answers locally,
and posts the answer back. The public request long-polls until the answer
arrives (up to 10 minutes).

## What you get

- `GET  /v1/models` and `POST /v1/chat/completions`, OpenAI-shaped
- Public model name: **`muse`**
- Bearer-key auth (your own generated key)
- Measured on the reference install: models ≈ 10s, chat ≈ 30s typical,
  worst case several minutes under queue load. **Clients need a timeout of
  ≥ 660s. Treat responses as non-streaming.**

## Quick start — let Muse do it

Give your Muse this repo's link and say:

> Set this up for me, end to end, following SETUP_FOR_MUSE.md.

It will run the phases, ask you for exactly one thing — a Cloudflare sign-in
(and a one-time API token created in that session) — and finish by printing
your **Base URL** and **API Key**.

## Quick start — manual

```bash
git clone https://github.com/wahyunuriman999/muse-public-api
cd muse-public-api

bash scripts/setup.sh            # generates all secrets locally (never committed)

# create the answering-worker schedule (see WORKER_CRON.md) — required,
# without it chat requests queue up unanswered

CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... \
  bash scripts/deploy-worker.sh  # wrangler deploy + writes WORKER_URL
# then delete that deploy token in the Cloudflare dashboard (see below)

bash scripts/start-all.sh        # bridge + proxy + poller
bash scripts/test-public.sh      # /v1/models end-to-end
bash scripts/test-public.sh --chat
bash scripts/show-connection.sh  # prints Base URL + API Key + Model
```

## Connecting your tools

Any OpenAI-compatible client (Cline, custom providers, the OpenAI SDK, …):

| Setting  | Value                                  |
|----------|----------------------------------------|
| Base URL | `https://<your-worker>.workers.dev/v1` |
| API Key  | the key from `show-connection.sh`      |
| Model    | `muse`                                 |

Set the client timeout as high as it allows (≥ 660s) and disable streaming.

## Security model

- No secret is ever committed: keys are generated locally into `.secrets/`
  and `tunnel/config.env` (mode 600, gitignored). The committed Worker
  source contains a `__INTERNAL_SECRET__` placeholder, substituted only
  into a local `.build/` copy at deploy time.
- The Cloudflare deploy token is **single-purpose**: create it, deploy,
  delete it in the dashboard. It cannot revoke itself via the API (the
  "Edit Cloudflare Workers" template has no token-management permission).
- The client API key only reaches the local proxy; the relay and poller
  secrets never leave the machine + Worker pair.

## Operational notes (learned in production)

- **Cloudflare blocks Python's default User-Agent (error 1010).** The poller
  sends a browser UA — keep it.
- **Never probe `/internal/jobs` by hand while testing.** That endpoint
  *claims* jobs for whoever calls it; manual probes steal queued requests
  from the poller and make healthy setups look broken.
- **The dashboard code editor cannot be automated** (Monaco), and a remote
  browser's clipboard is not your clipboard. Deploy with wrangler instead.
- Daemons are started detached (`setsid` + `disown`) so they survive their
  launcher session being killed. Run start scripts unpiped.
- About 1 in 5 polls through the VM's egress proxy may drop; the poller
  retries every 10s. That delays answers slightly — it does not lose them.

## Layout

```
relay/    bridge.py (queue-based OpenAI server, :20129) + start/janitor
proxy/    proxy.py (auth + model-alias front door, :20130)
tunnel/   muse-tunnel-worker.js (public ingress) + poller.py (VM side)
scripts/  setup · deploy-worker · start-all · test-public · show-connection
WORKER_CRON.md     the scheduled Muse job that answers requests
SETUP_FOR_MUSE.md  full agent brief — phases, gates, troubleshooting
```

## License

AGPL-3.0-only. Created by Wahyu Nur Iman.
