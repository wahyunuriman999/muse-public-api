#!/usr/bin/env python3
"""llm-proxy: authenticated OpenAI-compatible proxy directly in front of the
muse-relay bridge (Muse itself).

- Listens on 127.0.0.1:20130
- Requires:  Authorization: Bearer <PROXY_API_KEY>
- Forwards everything under /v1/* to the muse-relay bridge at
  127.0.0.1:20129, authenticating upstream with the relay bridge key.
  No 9router in this path: external callers reach Muse directly.
- /health is open (no auth) for local watchdog checks.

The relay is async: POST /v1/chat/completions queues a job and the
connection is held open (long-poll) until the Muse worker cron answers,
up to 600s. Clients must use a timeout of at least 660s (recommended 900s).

Env:
  PROXY_API_KEY   client-facing key (required)
  RELAY_KEY       upstream muse-relay bridge key (required)
  PROXY_PORT      default 20130
"""
import os
import re
import sys
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROXY_API_KEY = os.environ.get("PROXY_API_KEY", "")
RELAY_KEY = os.environ.get("RELAY_KEY", "")
UPSTREAM = "http://127.0.0.1:20129"
PORT = int(os.environ.get("PROXY_PORT", "20130"))
# Relay long-polls up to 600s; give it headroom.
UPSTREAM_TIMEOUT = 660

# Public-facing model names -> upstream relay model id
MODEL_ALIASES = {"muse": "muse-agent", "muse-agent": "muse-agent"}
REVERSE_ALIASES = {"muse-agent": "muse"}

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailer", "transfer-encoding", "upgrade"}


def _rewrite_sse_models(raw):
    """Rewrite upstream model ids to public names inside SSE data lines.

    Only the JSON "model" field of each data: chunk is touched, so a literal
    "muse-agent" inside the assistant's answer text is never corrupted.
    """
    out_lines = []
    for line in raw.split(b"\n"):
        stripped = line.strip()
        if stripped.startswith(b"data:") and b"[DONE]" not in stripped:
            payload_text = stripped[len(b"data:"):].strip()
            try:
                chunk = json.loads(payload_text.decode("utf-8"))
                if isinstance(chunk, dict) and chunk.get("model") in REVERSE_ALIASES:
                    chunk["model"] = REVERSE_ALIASES[chunk["model"]]
                    line = b"data: " + json.dumps(chunk).encode("utf-8")
            except Exception:
                pass
        out_lines.append(line)
    return b"\n".join(out_lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "llm-proxy/2.0"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("llm-proxy: " + fmt % args + "\n")

    def _auth_ok(self):
        auth = self.headers.get("Authorization", "")
        return auth == "Bearer " + PROXY_API_KEY and PROXY_API_KEY

    def _send_401(self):
        body = b'{"error":{"message":"invalid or missing API key","type":"auth_error"}}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/v1/"):
            body = b'{"error":"not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._auth_ok():
            self._send_401()
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        # Rewrite public model alias (e.g. "muse") to the upstream id ("muse-agent")
        want_stream = False
        if body and self.path in ("/v1/chat/completions", "/v1/completions"):
            try:
                data = json.loads(body.decode("utf-8"))
                if isinstance(data.get("model"), str) and data["model"] in MODEL_ALIASES:
                    data["model"] = MODEL_ALIASES[data["model"]]
                    body = json.dumps(data).encode("utf-8")
                want_stream = bool(data.get("stream"))
            except Exception:
                pass
        url = UPSTREAM + self.path
        req = urllib.request.Request(url, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length", "authorization"):
                continue
            req.add_header(k, v)
        req.add_header("Authorization", "Bearer " + RELAY_KEY)
        try:
            resp = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
            status, headers = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            status, headers, resp = e.code, e.headers, e
        rewrite_models = self.path == "/v1/models" and status == 200
        # Non-streamed completions: strip any trailing SSE "data: [DONE]" so the
        # body is clean JSON, and present the public model name.
        normalize_completion = (
            status == 200
            and self.path in ("/v1/chat/completions", "/v1/completions")
            and not want_stream
        )
        # The relay answers stream=true with a single complete SSE body, so it
        # is safe to buffer it and rewrite the echoed upstream model id to the
        # public name (prevents "muse-agent" leaking to clients).
        normalize_stream = (
            status == 200
            and self.path == "/v1/chat/completions"
            and want_stream
        )
        buffered = rewrite_models or normalize_completion or normalize_stream
        raw = b""
        if buffered:
            raw = resp.read()
            try:
                if normalize_completion:
                    raw = re.sub(rb"\s*data:\s*\[DONE\]\s*$", b"", raw)
                if normalize_stream:
                    raw = _rewrite_sse_models(raw)
                    payload = None
                else:
                    payload = json.loads(raw.decode("utf-8"))
                if payload is not None:
                    if rewrite_models:
                        for m in payload.get("data", []):
                            if m.get("id") in REVERSE_ALIASES:
                                m["id"] = REVERSE_ALIASES[m["id"]]
                    if normalize_completion and payload.get("model") in REVERSE_ALIASES:
                        payload["model"] = REVERSE_ALIASES[payload["model"]]
                    raw = json.dumps(payload).encode("utf-8")
            except Exception:
                # keep raw bytes as-is (already stripped if that succeeded)
                pass
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() in HOP_BY_HOP:
                continue
            if buffered and k.lower() == "content-length":
                continue
            self.send_header(k, v)
        if buffered:
            self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if buffered:
            self.wfile.write(raw)
        else:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle
    do_PUT = _handle
    do_PATCH = _handle


if __name__ == "__main__":
    if not PROXY_API_KEY or not RELAY_KEY:
        sys.exit("PROXY_API_KEY and RELAY_KEY must be set")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"llm-proxy listening on 127.0.0.1:{PORT} -> {UPSTREAM}", flush=True)
    srv.serve_forever()
