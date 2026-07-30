#!/usr/bin/env bash
# Lemely unattended build supervisor.
# Run inside tmux:  tmux new -s lemely './supervisor.sh'
# Stops when BUILD/STATE.md contains "status: COMPLETE" or after MAX_RUNS.

set -u
REPO="/home/sico/Code/Lemely"
NTFY="ntfy.sh/lemely-ErBPK7TIRGD1sQP5"
MODEL="opus"                    # Opus 5 orchestrator (strongest on Pro)
MAX_RUNS=500                    # absolute safety valve
BACKOFF_MIN=120                 # 2 min after a normal exit
BACKOFF_LIMIT=3600              # 60 min when a usage limit is suspected
LOGDIR="$REPO/BUILD/logs"

cd "$REPO" || exit 1
mkdir -p "$LOGDIR"

notify() { curl -s -H "Title: Lemely supervisor" -H "Priority: ${2:-default}" -d "$1" "$NTFY" >/dev/null 2>&1; }

FIRST_PROMPT="Read BUILD/MISSION.md end to end. It is your complete mission. Then read LEMELY_AUDIT.md and BUILD/STATE.md, and begin execution exactly as MISSION.md instructs."
RESUME_PROMPT="You are resuming an unattended build. Read BUILD/MISSION.md, BUILD/STATE.md, BUILD/DECISIONS.md and BUILD/BLOCKERS.md if present, and 'git log --oneline -15'. Clean up any dirty working tree with a wip commit, then continue from the first non-done task in STATE.md. Follow MISSION.md protocols exactly."

notify "Supervisor started on $(hostname)."
run=0
while [ "$run" -lt "$MAX_RUNS" ]; do
  run=$((run + 1))

  if grep -q "^status: COMPLETE" BUILD/STATE.md 2>/dev/null; then
    notify "BUILD COMPLETE after $run runs. DELIVERY.md is ready." high
    exit 0
  fi
  if grep -q "^status: HALTED" BUILD/STATE.md 2>/dev/null; then
    notify "Build HALTED by orchestrator. Check BUILD/BLOCKERS.md." high
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

  # Heuristic: usage-limit / rate-limit exits get a long backoff; retrying
  # hourly against a multi-day weekly limit is harmless and self-healing.
  if tail -n 60 "$LOG" | grep -qiE "usage limit|rate limit|limit reached|overloaded|429"; then
    notify "Run $run hit a usage limit (rc=$rc). Sleeping ${BACKOFF_LIMIT}s."
    sleep "$BACKOFF_LIMIT"
  elif [ "$rc" -ne 0 ]; then
    notify "Run $run exited rc=$rc (crash?). Sleeping ${BACKOFF_MIN}s. See $(basename "$LOG")."
    sleep "$BACKOFF_MIN"
  else
    # Clean exit = deliberate context-refresh checkpoint. Quick turnaround.
    sleep 30
  fi
done

notify "Supervisor hit MAX_RUNS=$MAX_RUNS safety valve. Stopping." high
exit 1
