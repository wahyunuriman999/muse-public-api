/**
 * muse-tunnel — public ingress for the Muse OpenAI-compatible API.
 *
 * Public (orchestrator):  https://<this-worker>.workers.dev/v1/*   (OpenAI-compatible)
 * Internal (this VM):     https://<this-worker>.workers.dev/internal/*  (poll + answer)
 *
 * How it works: every public /v1/* request becomes a job inside the Relay
 * Durable Object. The VM polls /internal/jobs every few seconds, forwards each
 * job to the local llm-proxy, and POSTs the answer to /internal/answer. The
 * public request waits (long-poll, up to 10 min) for that answer.
 *
 * Dashboard setup (free plan is enough):
 *  1. Workers & Pages -> Create Worker -> paste this file -> Deploy.
 *  2. Worker -> Settings -> Bindings -> Add binding -> Durable Object:
 *       Binding name: RELAY   |   Class name: Relay   -> Add, then Redeploy.
 *  3. Send the worker's public URL (https://<name>.<account>.workers.dev)
 *     to the person running the poller.
 */
const INTERNAL_SECRET = "__INTERNAL_SECRET__";
const CLIENT_API_KEY = "__PROXY_API_KEY__"; // substituted at deploy time (scripts/deploy-worker.sh)
const WAIT_MS = 600000; // 10 min, matches the relay's long-poll upstream
const CLAIM_LEASE_MS = 60000; // a claimed job with no answer after 60s is offered again
const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-max-age": "86400",
};

function b64encode(u8) {
  let s = "";
  for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
  return btoa(s);
}
function b64decode(b64) {
  const s = atob(b64);
  const b = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i);
  return b;
}
const SKIP_RESP_HEADERS = new Set(["content-length", "connection", "transfer-encoding", "keep-alive"]);

export class Relay {
  constructor(state, env) {
    this.jobs = new Map(); // id -> {method,path,headers,body,resolve,claimed}
  }

  async fetch(req) {
    const url = new URL(req.url);
    const path = url.pathname;

    // ---- internal: VM polls for pending jobs ----
    if (path === "/internal/jobs") {
      if (url.searchParams.get("secret") !== INTERNAL_SECRET)
        return new Response("forbidden", { status: 403 });
      const out = [];
      const now = Date.now();
      for (const [id, j] of this.jobs) {
        // Re-offer jobs whose claim lease expired (answer never arrived —
        // e.g. the poll response was truncated in transit). Without this a
        // single dropped transfer wedges the queue behind a lost job.
        if (!j.claimed || (j.claimed_at && now - j.claimed_at > CLAIM_LEASE_MS)) {
          j.claimed = true;
          j.claimed_at = now;
          out.push({ id, method: j.method, path: j.path, headers: j.headers, body: j.body });
        }
      }
      return Response.json({ jobs: out });
    }

    // ---- internal: VM posts an answer ----
    if (path === "/internal/answer" && req.method === "POST") {
      if (url.searchParams.get("secret") !== INTERNAL_SECRET)
        return new Response("forbidden", { status: 403 });
      let m;
      try { m = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
      const j = this.jobs.get(m.id);
      if (j) {
        this.jobs.delete(m.id);
        j.resolve({ status: m.status || 200, headers: m.headers || {}, body: m.body || "" });
      }
      return Response.json({ ok: true });
    }

    // ---- public API ----
    if (path !== "/health" && !path.startsWith("/v1/")) {
      return new Response('{"error":"not found"}',
        { status: 404, headers: { "content-type": "application/json" } });
    }
    const id = crypto.randomUUID();
    const headers = {};
    req.headers.forEach((v, k) => { headers[k] = v; });
    const body = b64encode(new Uint8Array(await req.arrayBuffer()));

    let timer;
    const answerP = new Promise((resolve) => {
      this.jobs.set(id, {
        method: req.method, path: path + url.search, headers, body,
        resolve, claimed: false, claimed_at: 0,
      });
      timer = setTimeout(() => {
        if (this.jobs.has(id)) {
          this.jobs.delete(id);
          resolve({
            status: 504,
            headers: { "content-type": "application/json" },
            body: b64encode(new TextEncoder().encode(
              '{"error":{"message":"upstream timeout","type":"timeout"}}')),
          });
        }
      }, WAIT_MS);
    });

    const ans = await answerP;
    clearTimeout(timer);
    const outHeaders = new Headers();
    for (const [k, v] of Object.entries(ans.headers || {})) {
      if (SKIP_RESP_HEADERS.has(k.toLowerCase())) continue;
      try { outHeaders.set(k, v); } catch {}
    }
    return new Response(b64decode(ans.body || ""), { status: ans.status || 200, headers: outHeaders });
  }
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    // CORS preflight — answered at the edge, never queued.
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // /v1/models is static — answer at the edge in <1s instead of queueing
    // it behind chat jobs (GUI clients probe it with short timeouts).
    // Auth mirrors the local proxy: wrong/missing key -> instant 401.
    if (req.method === "GET" && url.pathname === "/v1/models") {
      if (req.headers.get("authorization") !== "Bearer " + CLIENT_API_KEY) {
        return new Response(
          '{"error":{"message":"invalid or missing API key","type":"auth_error"}}',
          { status: 401, headers: { "content-type": "application/json", ...CORS_HEADERS } });
      }
      const body = JSON.stringify({
        object: "list",
        data: [{ id: "muse", object: "model", created: Math.floor(Date.now() / 1000), owned_by: "muse-relay" }],
      });
      return new Response(body, { headers: { "content-type": "application/json", ...CORS_HEADERS } });
    }

    const stub = env.RELAY.get(env.RELAY.idFromName("muse"));
    const resp = await stub.fetch(req);
    // Add CORS headers to queued responses too (browser/Electron clients).
    const headers = new Headers(resp.headers);
    for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v);
    return new Response(resp.body, { status: resp.status, headers });
  },
};
