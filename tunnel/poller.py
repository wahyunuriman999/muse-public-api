#!/usr/bin/env python3
"""ws-poller: bridges the Cloudflare Worker job queue to the local llm-proxy.

Every 10s it GETs /internal/jobs?secret=... from the Worker. Each job is
forwarded (in its own thread) to llm-proxy at 127.0.0.1:20130, and the
response is POSTed back to /internal/answer. The public request waits
(long-poll) inside the Worker until the answer arrives.

Config (config.env next to this script, mode 600):
  WORKER_URL=https://<name>.<account>.workers.dev
  POLL_SECRET=<same secret baked into the Worker>

Run: bash tunnel/start-poller.sh  (daemon, logs to poller.log)
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE_DIR, "config.env")
LOG = os.path.join(BASE_DIR, "poller.log")

PROXY = "http://127.0.0.1:20130"
INTERVAL = 10
PROXY_TIMEOUT = 660
SKIP_REQ_HEADERS = {"host", "content-length", "connection", "keep-alive"}
SKIP_RESP_HEADERS = {"content-length", "connection", "transfer-encoding", "keep-alive"}


def load_config():
    cfg = {}
    with open(CONFIG) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg["WORKER_URL"].rstrip("/"), cfg["POLL_SECRET"]


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with open(LOG, "a") as f:
            f.write(line)
    except OSError:
        pass
    sys.stderr.write("poller: " + line)


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def wapi(method, path, payload=None):
    # Transport is curl, not urllib: through this VM's egress proxy, urllib
    # transfers — especially large job payloads — get truncated mid-body
    # (IncompleteRead / RemoteDisconnected), while curl completes reliably.
    # Cloudflare also blocks non-browser user agents (error 1010), hence -A.
    url = WORKER_URL + path
    cmd = ["curl", "-s", "-m", "60", "--retry", "3", "--retry-all-errors",
           "-A", UA, "-X", method, "-w", "\n%{http_code}"]
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    p = subprocess.run(cmd + [url], input=data, capture_output=True, timeout=300)
    out = p.stdout
    nl = out.rfind(b"\n")
    try:
        status = int(out[nl + 1:].strip())
        body = out[:nl]
    except Exception:
        status, body = 0, out
    return status, body


def answer_job(jid, status, headers, raw):
    payload = {
        "id": jid,
        "status": status,
        "headers": {k: v for k, v in headers.items() if k.lower() not in SKIP_RESP_HEADERS},
        "body": base64.b64encode(raw).decode(),
    }
    s, _ = wapi("POST", f"/internal/answer?secret={POLL_SECRET}", payload)
    if s != 200:
        log(f"job {jid}: answer post -> {s}")


def handle(job):
    jid = job.get("id", "?")
    try:
        raw_body = base64.b64decode(job.get("body") or "")
        method = job.get("method", "POST")
        req = urllib.request.Request(
            PROXY + job.get("path", "/v1/models"),
            data=raw_body if method != "GET" else None,
            method=method,
        )
        for k, v in (job.get("headers") or {}).items():
            if k.lower() in SKIP_REQ_HEADERS:
                continue
            try:
                req.add_header(k, v)
            except Exception:
                pass
        try:
            resp = urllib.request.urlopen(req, timeout=PROXY_TIMEOUT)
            status, rheaders, rbody = resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as e:
            status, rheaders, rbody = e.code, dict(e.headers.items()), e.read()
        log(f"job {jid}: {method} {job.get('path')} -> {status} ({len(rbody)}b)")
        answer_job(jid, status, rheaders, rbody)
    except Exception as e:
        log(f"job {jid}: local error {e}")
        answer_job(jid, 502, {"content-type": "application/json"},
                   json.dumps({"error": {"message": "poller error", "type": "poller_error"}}).encode())


def main():
    global WORKER_URL, POLL_SECRET
    WORKER_URL, POLL_SECRET = load_config()
    log(f"poller started -> {WORKER_URL} (every {INTERVAL}s)")
    while True:
        try:
            s, body = wapi("GET", f"/internal/jobs?secret={POLL_SECRET}")
            if s == 200:
                try:
                    jobs = json.loads(body.decode()).get("jobs", [])
                except Exception:
                    jobs = []
                for job in jobs:
                    threading.Thread(target=handle, args=(job,), daemon=True).start()
                if jobs:
                    log(f"claimed {len(jobs)} job(s)")
            elif s == 403:
                log("poll: 403 (bad secret or worker not deployed)")
            else:
                log(f"poll: http {s}")
        except Exception as e:
            log(f"poll exception: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
