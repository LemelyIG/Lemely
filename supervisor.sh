#!/usr/bin/env bash
# Lemely unattended build supervisor.
# Run inside tmux:  tmux new -s lemely './supervisor.sh'
# Stops when BUILD/STATE.md contains "status: COMPLETE" or after MAX_RUNS.

set -u

# --------------------------- configuration ---------------------------------
REPO="/home/sico/Lemely"
NTFY_TOPIC="lemely-ErBPK7TIRGD1sQP5"
NTFY_URL="https://ntfy.sh"
REPO_URL="https://github.com/LemelyIG/Lemely"

MODEL_DEFAULT="sonnet"          # orchestrator default — cheap, capable enough
MODEL_ESCALATED="opus"          # used ONLY when STATE.md requests it (one run)

MAX_RUNS=500                    # absolute safety valve
BACKOFF_CRASH=120               # 2 min after a crash
BACKOFF_LIMIT_FALLBACK=3600     # used only when the reset time can't be parsed
LIMIT_RESUME_MARGIN=90          # seconds of slack added after a parsed reset
MAX_LIMIT_WAIT=$((14 * 3600))   # if a reset is further out than this, HALT
DEDUP_WINDOW_SECS=1800          # 30 min: suppress identical failure notices
HEARTBEAT_SECS=1200             # 20 min progress ping (updates in place)
WATCHDOG_MINUTES=45             # dead-man's switch horizon, refreshed each beat
ATTACH_MAX_BYTES=1900000        # stay under ntfy.sh's 2MB attachment cap

LOGDIR="$REPO/BUILD/logs"
NOTIFY_STATE="$REPO/BUILD/.supervisor_notify_state"   # "<epoch> <hash>"
RUNFILE="$REPO/BUILD/.supervisor_run"                 # run no. for the monitor
PHASEFILE="$REPO/BUILD/.supervisor_phase"             # last announced phase
REPORTMARK="$REPO/BUILD/.supervisor_reportmark"       # mtime marker for reports
STARTFILE="$REPO/BUILD/.supervisor_start"             # epoch of current run

cd "$REPO" || exit 1
mkdir -p "$LOGDIR"

# --------------------------- ntfy helpers ----------------------------------
# All publishing goes through the JSON endpoint so markdown, tags, priority,
# click, actions and sequence_id are available in a single request.

# ntfy_publish TITLE MESSAGE TAGS PRIORITY [ACTIONS_JSON] [SEQUENCE_ID] [DELAY]
ntfy_publish() {
  python3 - "$NTFY_URL" "$NTFY_TOPIC" "$REPO_URL" \
           "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" "${7:-}" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
url, topic, repo, title, message, tags, priority, actions, seq, delay = sys.argv[1:11]
p = {
    "topic": topic,
    "title": title,
    "message": message,
    "tags": [t for t in tags.split(",") if t],
    "priority": {"min":1,"low":2,"default":3,"high":4,"urgent":5}.get(priority, 3),
    "markdown": True,
    "click": repo,
}
if actions:
    try: p["actions"] = json.loads(actions)
    except Exception: pass
if seq:   p["sequence_id"] = seq
if delay: p["delay"] = delay
try:
    urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(p).encode(),
        headers={"Content-Type": "application/json"}), timeout=10)
except Exception:
    pass
PYEOF
}

# ntfy_attach FILE TITLE TAGS PRIORITY  — sends the tail of FILE as an attachment
ntfy_attach() {
  local file="$1" title="$2" tags="$3" priority="${4:-default}" tmp
  [ -f "$file" ] || return 0
  tmp="$(mktemp)"
  tail -c "$ATTACH_MAX_BYTES" "$file" > "$tmp"
  curl -s -T "$tmp" \
    -H "Filename: $(basename "$file")" \
    -H "Title: $title" -H "Tags: $tags" -H "Priority: $priority" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null 2>&1
  rm -f "$tmp"
}

ntfy_cancel() {  # cancel a scheduled message by sequence id
  curl -s -X DELETE "$NTFY_URL/$NTFY_TOPIC/$1" >/dev/null 2>&1
}

ACTIONS_REPO='[{"action":"view","label":"Open repo","url":"'"$REPO_URL"'"},{"action":"view","label":"Pull requests","url":"'"$REPO_URL"'/pulls"}]'

# --------------------------- progress helpers ------------------------------

state_field() { grep -m1 "^$1:" BUILD/STATE.md 2>/dev/null | sed "s/^$1:[[:space:]]*//"; }

progress_line() {
  local phase done total commit
  phase="$(state_field current_phase)"; phase="${phase:-?}"
  done="$(grep -c '^- \[x\]' BUILD/STATE.md 2>/dev/null || echo 0)"
  total="$(grep -c '^- \[' BUILD/STATE.md 2>/dev/null || echo 0)"
  commit="$(git log -1 --pretty=%s 2>/dev/null | cut -c1-72)"
  echo "**Phase $phase** — $done/$total tasks · last commit: \`${commit:-none}\`"
}

# --------------------------- failure dedup ---------------------------------

failure_signature() {
  tail -n 60 "$1" 2>/dev/null \
    | sed -E -e 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+([.,][0-9]+)?(Z|[+-][0-9:]+)?/<TS>/g' \
             -e 's/[0-9]{10,}/<NUM>/g' \
             -e 's#/home/[a-zA-Z0-9_./-]+#<PATH>#g' \
    | sha256sum | cut -d' ' -f1
}

should_notify_failure() {   # 0 = notify, 1 = suppress (same failure, <30 min)
  local sig now prev_epoch prev_sig age
  sig="$(failure_signature "$1")"; now="$(date +%s)"
  if [ -f "$NOTIFY_STATE" ]; then
    read -r prev_epoch prev_sig < "$NOTIFY_STATE"
    if [ -n "${prev_epoch:-}" ] && [ -n "${prev_sig:-}" ]; then
      age=$((now - prev_epoch))
      [ "$age" -lt "$DEDUP_WINDOW_SECS" ] && [ "$sig" = "$prev_sig" ] && return 1
    fi
  fi
  echo "$now $sig" > "$NOTIFY_STATE"
  return 0
}

# --------------------------- limit reset parsing ---------------------------
# There is no API for subscription limits, but the CLI prints the reset time in
# the error. Parse it; fall back to a fixed backoff if nothing matches.
# Prints seconds to wait on stdout, or nothing.

parse_reset_seconds() {
  python3 - "$1" <<'PYEOF' 2>/dev/null
import re, sys, datetime as dt
text = open(sys.argv[1], errors="ignore").read()[-20000:]
now = dt.datetime.now().astimezone()
cands = []

# "resets in 4 hours 23 minutes" / "try again in 45 minutes" / "in 2h 5m"
for m in re.finditer(r"(?:reset[s]?|try again|available again)\s*(?:in)?[:\s]+"
                     r"(?:(\d+)\s*(?:hours?|hrs?|h)\b)?\s*"
                     r"(?:(\d+)\s*(?:minutes?|mins?|m)\b)?", text, re.I):
    h, mi = m.group(1), m.group(2)
    if h or mi:
        cands.append(int(h or 0)*3600 + int(mi or 0)*60)

# "resets at 3pm" / "resets at 15:30" / "Resets at 3:00 PM" / "resets 4:10pm"
for m in re.finditer(r"reset[s]?\s*(?:at)?\s*[:]?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
                     text, re.I):
    hour = int(m.group(1)); minute = int(m.group(2) or 0); ap = (m.group(3) or "").lower()
    if ap == "pm" and hour != 12: hour += 12
    if ap == "am" and hour == 12: hour = 0
    if hour > 23: continue
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t <= now: t += dt.timedelta(days=1)
    cands.append(int((t - now).total_seconds()))

# ISO timestamp after a reset keyword, and unix epoch
for m in re.finditer(r"reset[^\n]{0,40}?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)", text, re.I):
    try:
        t = dt.datetime.fromisoformat(m.group(1).replace(" ", "T"))
        if t.tzinfo is None: t = t.astimezone()
        cands.append(int((t - now).total_seconds()))
    except Exception: pass
for m in re.finditer(r"reset[^\n]{0,40}?(1[6-9]\d{8})", text):
    cands.append(int(int(m.group(1)) - now.timestamp()))

cands = [c for c in cands if 0 < c < 8*24*3600]
if cands:
    print(max(cands))   # most conservative parsed value
PYEOF
}

# --------------------------- background monitor ----------------------------
# One long-lived loop: pushes an in-place progress heartbeat AND refreshes a
# dead-man's-switch scheduled message, so a laptop/power failure alerts you.

start_monitor() {
  (
    while :; do
      sleep "$HEARTBEAT_SECS"
      local_run="$(cat "$RUNFILE" 2>/dev/null || echo '?')"
      started="$(cat "$STARTFILE" 2>/dev/null || echo "$(date +%s)")"
      elapsed=$(( ( $(date +%s) - started ) / 60 ))
      ntfy_publish "Lemely — in progress" \
        "$(progress_line)
Run **$local_run** · ${elapsed}m elapsed" \
        "hourglass_flowing_sand" "low" "" "lemely-heartbeat"
      # dead man's switch: fires only if this loop stops refreshing it
      ntfy_publish "💀 Lemely supervisor stopped responding" \
        "No heartbeat for ${WATCHDOG_MINUTES}m — the machine or the supervisor died." \
        "skull" "urgent" "$ACTIONS_REPO" "lemely-watchdog" "${WATCHDOG_MINUTES}m"
    done
  ) &
  MONITOR_PID=$!
}

cleanup() {
  [ -n "${MONITOR_PID:-}" ] && kill "$MONITOR_PID" 2>/dev/null
  ntfy_cancel "lemely-watchdog"
}
trap cleanup EXIT INT TERM

# --------------------------- run loop --------------------------------------

FIRST_PROMPT="Read BUILD/MISSION.md end to end. It is your complete mission. Then read LEMELY_AUDIT.md and BUILD/STATE.md, and begin execution exactly as MISSION.md instructs."
RESUME_PROMPT="You are resuming an unattended build. Read BUILD/MISSION.md, BUILD/STATE.md, BUILD/DECISIONS.md and BUILD/BLOCKERS.md if present, and 'git log --oneline -15'. Clean up any dirty working tree with a wip commit, then continue from the first non-done task in STATE.md. Follow MISSION.md protocols exactly."

ntfy_publish "🚀 Lemely supervisor started" \
  "Host \`$(hostname)\` · default model **$MODEL_DEFAULT** (escalates to $MODEL_ESCALATED on request)
$(progress_line)" "rocket" "default" "$ACTIONS_REPO"

[ -f "$REPORTMARK" ] || touch "$REPORTMARK"
start_monitor

run=0
while [ "$run" -lt "$MAX_RUNS" ]; do
  run=$((run + 1)); echo "$run" > "$RUNFILE"

  case "$(state_field status)" in
    COMPLETE)
      ntfy_publish "🎉 Lemely BUILD COMPLETE" \
        "Finished after **$run** runs. \`DELIVERY.md\` is in the repo.
$(progress_line)" "tada,white_check_mark" "urgent" "$ACTIONS_REPO"
      ntfy_attach "$REPO/DELIVERY.md" "DELIVERY.md" "page_facing_up" "default"
      exit 0 ;;
    HALTED)
      ntfy_publish "🛑 Lemely build HALTED" \
        "Orchestrator halted the build. See \`BUILD/BLOCKERS.md\`." \
        "octagonal_sign" "urgent" "$ACTIONS_REPO"
      ntfy_attach "$REPO/BUILD/BLOCKERS.md" "BLOCKERS.md" "warning" "high"
      exit 1 ;;
  esac

  # Model selection: Sonnet unless STATE.md asks for one escalated run.
  MODEL="$MODEL_DEFAULT"
  if [ "$(state_field next_run_model)" = "opus" ]; then
    MODEL="$MODEL_ESCALATED"
    sed -i 's/^next_run_model:.*/next_run_model: sonnet/' BUILD/STATE.md
    ntfy_publish "🧠 Escalating to Opus for run $run" \
      "The orchestrator requested Opus for the next task.
$(progress_line)" "brain" "default"
  fi

  if [ "$run" -eq 1 ] && [ ! -f BUILD/JOURNAL.md ]; then
    PROMPT="$FIRST_PROMPT"
  else
    PROMPT="$RESUME_PROMPT"
  fi

  LOG="$LOGDIR/run-$(printf '%04d' "$run")-$(date +%Y%m%d-%H%M%S).log"
  date +%s > "$STARTFILE"
  echo "=== run $run starting $(date -Is) model=$MODEL ===" | tee -a "$LOG"

  claude -p "$PROMPT" --model "$MODEL" \
    --dangerously-skip-permissions --verbose >>"$LOG" 2>&1
  rc=$?

  echo "=== run $run exited rc=$rc $(date -Is) ===" >>"$LOG"
  mins=$(( ( $(date +%s) - $(cat "$STARTFILE") ) / 60 ))

  # --- phase transition? -----------------------------------------------
  phase_now="$(state_field current_phase)"
  phase_prev="$(cat "$PHASEFILE" 2>/dev/null || echo '')"
  if [ -n "$phase_now" ] && [ "$phase_now" != "$phase_prev" ]; then
    echo "$phase_now" > "$PHASEFILE"
    [ -n "$phase_prev" ] && ntfy_publish "✅ Phase $phase_prev complete" \
      "Now starting **Phase $phase_now**.
$(progress_line)" "white_check_mark" "high" "$ACTIONS_REPO"
  fi

  # --- new milestone reports? ------------------------------------------
  while IFS= read -r rpt; do
    [ -n "$rpt" ] && ntfy_attach "$rpt" "📄 $(dirname "${rpt#./}") report" "clipboard" "high"
  done < <(find reports -name 'REPORT.md' -newer "$REPORTMARK" 2>/dev/null)
  touch "$REPORTMARK"

  # --- outcome ----------------------------------------------------------
  # MODIFIED: Added "session limit" to the grep check below
  if tail -n 80 "$LOG" | grep -qiE "session limit|usage limit|rate limit|limit reached|overloaded|429"; then
    wait_secs="$(parse_reset_seconds "$LOG")"
    if [ -n "$wait_secs" ]; then
      wait_secs=$((wait_secs + LIMIT_RESUME_MARGIN))
      precision="parsed from the limit message"
    else
      wait_secs="$BACKOFF_LIMIT_FALLBACK"
      precision="estimated (no reset time in the message)"
    fi

    if [ "$wait_secs" -gt "$MAX_LIMIT_WAIT" ]; then
      ntfy_publish "🛑 Long limit window — supervisor stopping" \
        "Reset is ~$((wait_secs / 3600))h away (likely the weekly cap), beyond the ${MAX_LIMIT_WAIT}s ceiling.
Stopping cleanly. Nothing is lost — rerun \`./supervisor.sh\` after the reset.
$(progress_line)" "octagonal_sign" "urgent" "$ACTIONS_REPO"
      exit 0
    fi

    if should_notify_failure "$LOG"; then
      ntfy_publish "⏳ Usage limit — waiting for reset" \
        "$(progress_line)
Resuming in **$((wait_secs / 60))m** (~$(date -d "+$wait_secs seconds" '+%H:%M')), $precision.
Ran ${mins}m before hitting the wall." \
        "hourglass_flowing_sand" "low" "" "lemely-limit"
    fi
    sleep "$wait_secs"
    ntfy_publish "▶️ Limit reset — resuming" \
      "$(progress_line)" "arrow_forward" "low" "" "lemely-limit"

  elif [ "$rc" -ne 0 ]; then
    if should_notify_failure "$LOG"; then
      ntfy_publish "⚠️ Run $run crashed (rc=$rc)" \
        "$(progress_line)
Ran ${mins}m · retrying in $((BACKOFF_CRASH / 60))m · log attached." \
        "warning" "high" "$ACTIONS_REPO"
      ntfy_attach "$LOG" "Crash log — run $run (rc=$rc)" "page_facing_up" "high"
    fi
    sleep "$BACKOFF_CRASH"

  else
    # Clean exit = deliberate context-refresh checkpoint.
    ntfy_publish "🔄 Run $run checkpointed" \
      "$(progress_line)
Context refresh after ${mins}m — restarting immediately." \
      "recycle" "min" "" "lemely-checkpoint"
    sleep 20
  fi
done

ntfy_publish "🛑 Supervisor hit MAX_RUNS=$MAX_RUNS" \
  "Safety valve tripped. $(progress_line)" "octagonal_sign" "urgent" "$ACTIONS_REPO"
exit 1
