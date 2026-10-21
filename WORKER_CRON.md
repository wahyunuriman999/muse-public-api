# The answering worker — the one schedule that makes this an API

The relay bridge does not call a model API. Incoming chat requests are
written as job files to `relay/queue/`, and **a scheduled agent job — Muse
itself — answers them**. That is the whole point: callers reach the actual
agent, with its memory, tools and skills, not a raw model endpoint.

## Create this schedule in Muse

Create a recurring agent schedule:

- **Interval:** every 2 minutes
- **Title:** `muse-relay worker`
- **Body (use verbatim, only adjust the clone path):**

```text
muse-relay worker: look in <CLONE>/relay/queue/ for *.json job files.
If there are none, finish silently — say nothing, report nothing.

For each job file:
1. Read it: {"id": "<job id>", "messages": [ ... OpenAI chat messages ... ]}.
2. Compose your reply to that conversation as yourself — you are the API
   backend (public model name "muse"). Reply to the user's latest message,
   in context of the full messages array. Plain text, no meta commentary
   about being a relay.
3. Write <CLONE>/relay/done/<id>.json containing exactly:
   {"content": "<your reply>"}
4. Delete the job file from relay/queue/.

Handle every queued job in the run. If a job file is malformed, write its
done file with a short error explanation as "content" and delete the job.
```

## Recommended second schedule (housekeeping)

- **Interval:** every 30 minutes
- **Body:** `Run: bash <CLONE>/relay/janitor.sh` — or any exec schedule your
  runtime supports. It removes answered files and stale jobs older than
  30 minutes.

## Notes

- Latency is honest: worst case ≈ schedule interval + answer time.
  In production this stack answers most requests in under a minute when the
  worker fires promptly; document 1–6 minutes to users.
- The bridge deduplicates identical message payloads within 10 minutes, so
  client retries attach to the pending job instead of spawning duplicates.
- Done files are intentionally not deleted by the bridge (deduplicated
  waiters may still need them) — the janitor cleans them up.
