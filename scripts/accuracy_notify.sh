#!/usr/bin/env bash
# scripts/accuracy_notify.sh — one-shot notifier for the accuracy programme.
#
#   scripts/accuracy_notify.sh <title> <message> [tags] [priority]
#
#   tags:     comma-separated ntfy tags/emoji names, e.g. "test_tube,warning"
#   priority: min | low | default | high | urgent          (default: default)
#
# For any agent or hook that needs to ping the human from Bash mid-run.
# ALWAYS exits 0: the ntfy server at home-server:7532 has been observed
# refusing connections, and a notification must never fail (or block) the
# caller. Do not add retries or error output here.
#
# From PYTHON, do not shell out to this — use the in-repo client
# lemely/runtime/notify.py (and budget_notify), driven by LEMELY_NTFY_TOPIC.
#
# Never attach or embed content from tests/fixtures/real-papers/ in a
# notification: those PDFs are a minor's real handwritten exam scripts.
set -u

NTFY_URL="http://home-server:7532"
NTFY_TOPIC="lemely-acc-EF5H6SKKGxyJseM"

python3 - "$NTFY_URL" "$NTFY_TOPIC" "${1:-notify}" "${2:-}" "${3:-}" "${4:-default}" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
url, topic, title, message, tags, priority = sys.argv[1:7]
p = {
    "topic": topic, "title": title, "message": message,
    "tags": [t for t in tags.split(",") if t],
    "priority": {"min":1,"low":2,"default":3,"high":4,"urgent":5}.get(priority, 3),
    "markdown": True,
}
try:
    urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(p).encode(),
        headers={"Content-Type": "application/json"}), timeout=10)
except Exception:
    pass
PYEOF
exit 0
