#!/usr/bin/env bash
# Lemely unattended build supervisor.
# Run inside tmux:  tmux new -s lemely './supervisor.sh'
# Stops when BUILD/STATE.md contains "status: COMPLETE" or after MAX_RUNS.

set -u
REPO="/home/sico/Code/Lemely"
NTFY_TOPIC="lemely-ErBPK7TIRGD1sQP5"
NTFY_URL="https://ntfy.sh"
REPO_URL="https://github.com/LemelyIG/Lemely"
MODEL="opus"                    # Opus 5 orchestrator (strongest on Pro)
MAX_RUNS=500                    # absolute safety valve
BACKOFF_MIN=120                 # 2 min after a normal exit
BACKOFF_LIMIT=3600              # 60 min when a usage limit is suspected
DEDUP_WINDOW_SECS=1800          # 30 min: suppress repeat notifications for the
                                 # same failure signature within this window
LOGDIR="$REPO/BUILD/logs"
NOTIFY_STATE="$REPO/BUILD/.supervisor_notify_state"   # "<epoch> <hash>"
ATTACH_MAX_BYTES=1900000        # stay under ntfy.sh's 2MB attachment cap

cd "$REPO" || exit 1
mkdir -p "$LOGDIR"

# ---------------------------------------------------------------------------
# ntfy helpers
# ---------------------------------------------------------------------------

# ntfy_publish TITLE MESSAGE TAGS PRIORITY [ACTIONS_JSON]
# TAGS: comma-separated ntfy tag/emoji short-codes, e.g. "rocket,white_check_mark"
# PRIORITY: min|low|default|high|urgent
# ACTIONS_JSON: optional JSON array literal for the "actions" field (already valid JSON)
ntfy_publish() {
  local title="$1" message="$2" tags="$3" priority="$4" actions="${5:-}"
  python3 - "$NTFY_URL" "$NTFY_TOPIC" "$title" "$message" "$tags" "$priority" "$REPO_URL" "$actions" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
ntfy_url, topic, title, message, tags, priority, repo_url, actions_raw = sys.argv[1:9]
payload = {
    "topic": topic,
    "title": title,
    "message": message,
    "tags": [t for t in tags.split(",") if t],
    "priority": {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}.get(priority, 3),
    "markdown": True,
    "click": repo_url,
}
if actions_raw:
    try:
        payload["actions"] = json.loads(actions_raw)
    except Exception:
        pass
req = urllib.request.Request(ntfy_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=10)
except Exception:
    pass
PYEOF
}

# ntfy_attach FILE TITLE TAGS PRIORITY
# Sends FILE (truncated to ATTACH_MAX_BYTES from the tail) as an ntfy attachment.
ntfy_attach() {
  local file="$1" title="$2" tags="$3" priority="${4:-default}"
  [ -f "$file" ] || return 0
  local tmp
  tmp="$(mktemp)"
  tail -c "$ATTACH_MAX_BYTES" "$file" > "$tmp"
  curl -s \
    -T "$tmp" \
    -H "Filename: $(basename "$file")" \
    -H "Title: $title" \
    -H "Tags: $tags" \
    -H "Priority: $priority" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null 2>&1
  rm -f "$tmp"
}

# failure_signature LOG -> stable-ish hash of the tail, timestamps/paths scrubbed
failure_signature() {
  local log="$1"
  tail -n 60 "$log" 2>/dev/null \
    | sed -E \
        -e 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+([.,][0-9]+)?(Z|[+-][0-9:]+)?/<TS>/g' \
        -e 's/[0-9]{10,}/<NUM>/g' \
        -e 's#/home/[a-zA-Z0-9_./-]+#<PATH>#g' \
    | sha256sum | cut -d' ' -f1
}

# should_notify_failure LOG -> 0 (yes, notify) or 1 (suppress, seen recently)
# Always updates NOTIFY_STATE when it returns 0.
should_notify_failure() {
  local log="$1"
  local sig; sig="$(failure_signature "$log")"
  local now; now="$(date +%s)"
  if [ -f "$NOTIFY_STATE" ]; then
    read -r prev_epoch prev_sig < "$NOTIFY_STATE"
    if [ -n "${prev_epoch:-}" ] && [ -n "${prev_sig:-}" ]; then
      local age=$((now - prev_epoch))
      if [ "$age" -lt "$DEDUP_WINDOW_SECS" ] && [ "$sig" = "$prev_sig" ]; then
        return 1
      fi
    fi
  fi
  echo "$now $sig" > "$NOTIFY_STATE"
  return 0
}

ACTIONS_VIEW_REPO='[{"action":"view","label":"Open repo","url":"'"$REPO_URL"'"}]'

FIRST_PROMPT="Read BUILD/MISSION.md end to end. It is your complete mission. Then read LEMELY_AUDIT.md and BUILD/STATE.md, and begin execution exactly as MISSION.md instructs."
RESUME_PROMPT="You are resuming an unattended build. Read BUILD/MISSION.md, BUILD/STATE.md, BUILD/DECISIONS.md and BUILD/BLOCKERS.md if present, and 'git log --oneline -15'. Clean up any dirty working tree with a wip commit, then continue from the first non-done task in STATE.md. Follow MISSION.md protocols exactly."

ntfy_publish "🚀 Lemely supervisor started" "Supervisor started on \`$(hostname)\`. Model: **$MODEL**." "rocket" "default"

run=0
while [ "$run" -lt "$MAX_RUNS" ]; do
  run=$((run + 1))

  if grep -q "^status: COMPLETE" BUILD/STATE.md 2>/dev/null; then
    ntfy_publish "🎉 Lemely BUILD COMPLETE" "Completed after **$run** runs. \`DELIVERY.md\` is ready in the repo." "tada,white_check_mark" "urgent" "$ACTIONS_VIEW_REPO"
    exit 0
  fi
  if grep -q "^status: HALTED" BUILD/STATE.md 2>/dev/null; then
    ntfy_publish "🛑 Lemely build HALTED" "Orchestrator set status: HALTED. Check \`BUILD/BLOCKERS.md\`." "octagonal_sign" "urgent" "$ACTIONS_VIEW_REPO"
    exit 1
  fi

  if [ "$run" -eq 1 ] && [ ! -f BUILD/JOURNAL.md ]; then
    PROMPT="$FIRST_PROMPT"
  else
    PROMPT="$RESUME_PROMPT"
  fi

  LOG="$LOGDIR/run-$(printf '%04d' "$run")-$(date +%Y%m%d-%H%M%S).log"
  echo "=== run $run starting $(date -Is) ===" | tee -a "$LOG"

  claude -p "$PROMPT" \
    --model "$MODEL" \
    --dangerously-skip-permissions \
    --verbose \
    >>"$LOG" 2>&1
  rc=$?

  echo "=== run $run exited rc=$rc $(date -Is) ===" >>"$LOG"

  if tail -n 60 "$LOG" | grep -qiE "usage limit|rate limit|limit reached|overloaded|429"; then
    if should_notify_failure "$LOG"; then
      ntfy_publish "⏳ Run $run hit a usage limit" "rc=**$rc**. Sleeping **${BACKOFF_LIMIT}s** before retry. Log: \`$(basename "$LOG")\`" "hourglass_flowing_sand" "low"
    fi
    sleep "$BACKOFF_LIMIT"
  elif [ "$rc" -ne 0 ]; then
    if should_notify_failure "$LOG"; then
      ntfy_publish "⚠️ Run $run crashed (rc=$rc)" "Sleeping **${BACKOFF_MIN}s** before retry. Log tail attached." "warning" "high" "$ACTIONS_VIEW_REPO"
      ntfy_attach "$LOG" "Crash log — run $run (rc=$rc)" "page_facing_up" "high"
    fi
    sleep "$BACKOFF_MIN"
  else
    sleep 30
  fi
done

ntfy_publish "🛑 Lemely supervisor: MAX_RUNS reached" "Hit the MAX_RUNS=$MAX_RUNS safety valve. Stopping." "octagonal_sign" "urgent" "$ACTIONS_VIEW_REPO"
exit 1
