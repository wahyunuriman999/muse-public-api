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
const WAIT_MS = 600000; // 10 min, matches the relay's long-poll upstream

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
      for (const [id, j] of this.jobs) {
        if (!j.claimed) {
          j.claimed = true;
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
        resolve, claimed: false,
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
    const stub = env.RELAY.get(env.RELAY.idFromName("muse"));
    return stub.fetch(req);
  },
};
