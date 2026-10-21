#!/usr/bin/env bash
# janitor.sh — relay housekeeping; run periodically (e.g. every 30 min via a
# scheduled task): drop answered files older than 30 min, move unanswered
# queue jobs older than 30 min to stale/.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
find "$DIR/done" -name "*.json" -mmin +30 -delete 2>/dev/null
for f in "$DIR"/queue/*.json; do
  [ -e "$f" ] || continue
  if [ "$(( $(date +%s) - $(stat -c %Y "$f") ))" -gt 1800 ]; then
    mv "$f" "$DIR/stale/" 2>/dev/null
    echo "$(date '+%F %T') moved stale job $(basename "$f")" >> "$DIR/janitor.log"
  fi
done
