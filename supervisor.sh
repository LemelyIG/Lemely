#!/usr/bin/env bash
# Lemely unattended build supervisor.
# Run inside tmux:  tmux new -s lemely './supervisor.sh'
# Stops when BUILD/STATE.md contains "status: COMPLETE" or after MAX_RUNS.

set -u

# --------------------------- configuration ---------------------------------
REPO="/home/sico/Lemely"
NTFY_TOPIC="lemely-ErBPK7TIRGD1sQP5"
CTRL_TOPIC="lemely-ctl-9QmZR4vXpL2wDA7t"   # you PUBLISH here to steer the run
NTFY_URL="https://ntfy.sh"
REPO_URL="https://github.com/LemelyIG/Lemely"

MODEL="opus"                    # orchestrator model — Opus for everything

MAX_RUNS=500                    # absolute safety valve
BACKOFF_CRASH=120               # 2 min after a crash
BACKOFF_LIMIT_FALLBACK=3600     # used only when the reset time can't be parsed
LIMIT_RESUME_MARGIN=90          # seconds of slack added after a parsed reset
MAX_LIMIT_WAIT=$((14 * 3600))   # if a reset is further out than this, HALT
DEDUP_WINDOW_SECS=1800          # 30 min: suppress identical failure notices
HEARTBEAT_SECS=600              # 10 min progress ping (updates in place)
STALL_BEATS=3                   # beats with no commit + no state change = stall
WATCHDOG_MINUTES=35             # dead-man's switch horizon, refreshed each beat
DIGEST_SECS=$((24 * 3600))      # daily digest cadence
ATTACH_MAX_BYTES=1900000        # stay under ntfy.sh's 2MB attachment cap
MAX_NEW_SHOTS=3                 # newest screenshots to push per run

LOGDIR="$REPO/BUILD/logs"
NOTIFY_STATE="$REPO/BUILD/.supervisor_notify_state"
RUNFILE="$REPO/BUILD/.supervisor_run"
PHASEFILE="$REPO/BUILD/.supervisor_phase"
REPORTMARK="$REPO/BUILD/.supervisor_reportmark"
SHOTMARK="$REPO/BUILD/.supervisor_shotmark"
BLOCKMARK="$REPO/BUILD/.supervisor_blockmark"
STARTFILE="$REPO/BUILD/.supervisor_start"
DIGESTFILE="$REPO/BUILD/.supervisor_digest"
STALLFILE="$REPO/BUILD/.supervisor_stall"
INBOX="$REPO/BUILD/INBOX.md"
PAUSEFILE="$REPO/BUILD/PAUSE"
CLAUDE_PIDFILE="$REPO/BUILD/.supervisor_claude_pid"

cd "$REPO" || exit 1
mkdir -p "$LOGDIR"

# --------------------------- ntfy helpers ----------------------------------

# ntfy_publish TITLE MESSAGE TAGS PRIORITY [ACTIONS_JSON] [SEQUENCE_ID] [DELAY] [CLICK_URL]
ntfy_publish() {
  python3 - "$NTFY_URL" "$NTFY_TOPIC" \
           "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" "${7:-}" "${8:-$REPO_URL}" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
url, topic, title, message, tags, priority, actions, seq, delay, click = sys.argv[1:11]
p = {
    "topic": topic, "title": title, "message": message,
    "tags": [t for t in tags.split(",") if t],
    "priority": {"min":1,"low":2,"default":3,"high":4,"urgent":5}.get(priority, 3),
    "markdown": True, "click": click,
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

# ntfy_attach FILE TITLE TAGS PRIORITY [CLICK_URL] — sends the tail of FILE
ntfy_attach() {
  local file="$1" title="$2" tags="$3" priority="${4:-default}" click="${5:-$REPO_URL}" tmp
  [ -f "$file" ] || return 0
  tmp="$(mktemp)"
  case "$file" in
    *.png|*.jpg|*.jpeg|*.webp) cp "$file" "$tmp" ;;   # binaries: send whole
    *) tail -c "$ATTACH_MAX_BYTES" "$file" | strip_ansi > "$tmp" ;;
  esac
  [ "$(stat -c%s "$tmp" 2>/dev/null || echo 0)" -gt "$ATTACH_MAX_BYTES" ] && { rm -f "$tmp"; return 0; }
  curl -s -T "$tmp" \
    -H "Filename: $(basename "$file")" \
    -H "Title: $title" -H "Tags: $tags" -H "Priority: $priority" -H "Click: $click" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null 2>&1
  rm -f "$tmp"
}

ntfy_cancel() { curl -s -X DELETE "$NTFY_URL/$CTRL_TOPIC/$1" >/dev/null 2>&1
                curl -s -X DELETE "$NTFY_URL/$NTFY_TOPIC/$1" >/dev/null 2>&1; }

strip_ansi() { sed -r 's/\x1B\[[0-9;]*[a-zA-Z]//g; s/\x1B\][^\x07]*\x07//g'; }

CTRL_URL="$NTFY_URL/$CTRL_TOPIC"
ctrl_action() { printf '{"action":"http","label":"%s","url":"%s","method":"POST","body":"%s"}' "$1" "$CTRL_URL" "$2"; }
view_action() { printf '{"action":"view","label":"%s","url":"%s"}' "$1" "$2"; }

# --------------------------- state & progress ------------------------------

state_field() { grep -m1 "^$1:" BUILD/STATE.md 2>/dev/null | sed "s/^$1:[[:space:]]*//"; }

phase_name() {
  case "$1" in
    0) echo "Foundation repair" ;;
    1) echo "Database + Auth" ;;
    2) echo "Core correction loop" ;;
    2.5) echo "Design system + frontend quality" ;;
    3) echo "Teacher + Parent" ;;
    4) echo "Content + study plans" ;;
    5) echo "Engagement layer" ;;
    6) echo "Hardening + ship" ;;
    *) echo "Phase $1" ;;
  esac
}

progress_bar() {   # $1=done $2=total, renders a 10-cell bar with percentage
  local done="${1:-0}" total="${2:-0}" pct filled i out=""
  [ "$total" -le 0 ] && { echo "—"; return; }
  pct=$(( done * 100 / total )); filled=$(( pct / 10 ))
  for i in $(seq 1 10); do
    [ "$i" -le "$filled" ] && out="${out}▓" || out="${out}░"
  done
  echo "$out ${pct}% (${done}/${total})"
}

# Counts tasks in the CURRENT phase section only (between its ## header and the next)
phase_task_counts() {
  python3 - "$(state_field current_phase)" <<'PYEOF' 2>/dev/null
import re, sys
phase = sys.argv[1].strip()
try: text = open("BUILD/STATE.md").read()
except Exception: print("0 0 0 "); raise SystemExit
blocks = re.split(r"^## ", text, flags=re.M)
cur = next((b for b in blocks if b.lower().startswith(f"phase {phase.lower()}")), "")
done = len(re.findall(r"^- \[x\]", cur, re.M))
doing = re.findall(r"^- \[~\] *(.*)$", cur, re.M)
blocked = len(re.findall(r"^- \[!\]", cur, re.M))
total = len(re.findall(r"^- \[", cur, re.M))
print(done, total, blocked, (doing[0][:70] if doing else ""))
PYEOF
}

progress_block() {   # the standard, information-dense body prefix
  local phase pn counts done total blocked doing commits spend
  phase="$(state_field current_phase)"; phase="${phase:-?}"
  pn="$(phase_name "$phase")"
  counts="$(phase_task_counts)"
  done="$(echo "$counts" | awk '{print $1}')"; total="$(echo "$counts" | awk '{print $2}')"
  blocked="$(echo "$counts" | awk '{print $3}')"
  doing="$(echo "$counts" | cut -d' ' -f4-)"
  spend="$(state_field gemini_spend_usd)"
  printf '**Phase %s — %s**\n`%s`\n' "$phase" "$pn" "$(progress_bar "${done:-0}" "${total:-0}")"
  [ -n "$doing" ] && printf '▸ Now: %s\n' "$doing"
  [ "${blocked:-0}" -gt 0 ] 2>/dev/null && printf '⚠ %s blocked task(s)\n' "$blocked"
  [ -n "$spend" ] && printf '· Gemini spend: $%s of $8.00\n' "$spend"
}

commit_url() { echo "$REPO_URL/commit/$(git rev-parse HEAD 2>/dev/null)"; }

recent_commits() {   # $1 = how many
  git log -"${1:-3}" --pretty='· `%h` %s' 2>/dev/null | cut -c1-90
}

run_diff_summary() {  # $1 = sha at run start
  local sha="$1" n stat
  [ -z "$sha" ] && return 0
  n="$(git rev-list --count "$sha"..HEAD 2>/dev/null || echo 0)"
  stat="$(git diff --shortstat "$sha"..HEAD 2>/dev/null)"
  [ "$n" = "0" ] && { echo "No commits this run."; return; }
  printf '**%s commit(s)**%s\n%s\n' "$n" "${stat:+ —$stat}" "$(git log "$sha"..HEAD --pretty='· `%h` %s' 2>/dev/null | head -5 | cut -c1-90)"
}

# --------------------------- failure dedup ---------------------------------

failure_signature() {
  tail -n 60 "$1" 2>/dev/null | strip_ansi \
    | sed -E -e 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+([.,][0-9]+)?(Z|[+-][0-9:]+)?/<TS>/g' \
             -e 's/[0-9]{10,}/<NUM>/g' -e 's#/home/[a-zA-Z0-9_./-]+#<PATH>#g' \
    | sha256sum | cut -d' ' -f1
}

should_notify_failure() {
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

parse_reset_seconds() {
  python3 - "$1" <<'PYEOF' 2>/dev/null
import re, sys, datetime as dt
text = open(sys.argv[1], errors="ignore").read()[-20000:]
now = dt.datetime.now().astimezone(); cands = []
for m in re.finditer(r"(?:reset[s]?|try again|available again)\s*(?:in)?[:\s]+"
                     r"(?:(\d+)\s*(?:hours?|hrs?|h)\b)?\s*(?:(\d+)\s*(?:minutes?|mins?|m)\b)?", text, re.I):
    h, mi = m.group(1), m.group(2)
    if h or mi: cands.append(int(h or 0)*3600 + int(mi or 0)*60)
for m in re.finditer(r"reset[s]?\s*(?:at)?[:\s]+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I):
    hour = int(m.group(1)); minute = int(m.group(2) or 0); ap = (m.group(3) or "").lower()
    if ap == "pm" and hour != 12: hour += 12
    if ap == "am" and hour == 12: hour = 0
    if hour > 23: continue
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t <= now: t += dt.timedelta(days=1)
    cands.append(int((t - now).total_seconds()))
for m in re.finditer(r"reset[^\n]{0,40}?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)", text, re.I):
    try:
        t = dt.datetime.fromisoformat(m.group(1).replace(" ", "T"))
        if t.tzinfo is None: t = t.astimezone()
        cands.append(int((t - now).total_seconds()))
    except Exception: pass
for m in re.finditer(r"reset[^\n]{0,40}?(1[6-9]\d{8})", text):
    cands.append(int(int(m.group(1)) - now.timestamp()))
cands = [c for c in cands if 0 < c < 8*24*3600]
if cands: print(max(cands))
PYEOF
}


# do_sync [branch] — push local work to GitHub so you can review it remotely.
# Pushes every local branch that is ahead of its remote (or has no remote yet).
# Never force-pushes, never commits for you, never touches the working tree.
do_sync() {
  local target="${1:-}" branches b ahead lines="" pushed=0 failed=0 skipped=0 dirty prs
  git fetch --prune origin >/dev/null 2>&1
  if [ -n "$target" ]; then branches="$target"
  else branches="$(git for-each-ref --format='%(refname:short)' refs/heads/ 2>/dev/null)"; fi

  for b in $branches; do
    if git rev-parse --verify "origin/$b" >/dev/null 2>&1; then
      ahead="$(git rev-list --count "origin/$b..$b" 2>/dev/null || echo 0)"
    else
      ahead="new"
    fi
    if [ "$ahead" = "0" ]; then skipped=$((skipped + 1)); continue; fi
    if git push -u origin "$b" >>"$LOGDIR/sync.log" 2>&1; then
      lines="$lines
· \`$b\` — $([ "$ahead" = "new" ] && echo "new branch pushed" || echo "$ahead commit(s) pushed")"
      pushed=$((pushed + 1))
    else
      lines="$lines
· \`$b\` — ✗ push rejected (see sync.log)"
      failed=$((failed + 1))
    fi
  done

  dirty="$(git status --porcelain 2>/dev/null | wc -l)"
  prs=""
  command -v gh >/dev/null 2>&1 && prs="$(gh pr list --state open 2>/dev/null | wc -l)"

  ntfy_publish "$([ "$failed" -gt 0 ] && echo '⚠️ Synced with issues' || echo '🔄 Synced to GitHub')" \
    "$(progress_block)
**$pushed branch(es) pushed**$([ "$skipped" -gt 0 ] && echo ", $skipped already up to date")$([ "$failed" -gt 0 ] && echo ", $failed failed")
${lines:-
· Nothing to push — everything is already on GitHub.}
$([ "${dirty:-0}" -gt 0 ] && echo "
⚠ $dirty uncommitted file(s) still local — the agent commits its own work, so these will go up on its next checkpoint.")
$([ -n "$prs" ] && echo "
$prs open pull request(s).")" \
    "$([ "$failed" -gt 0 ] && echo 'warning' || echo 'arrows_counterclockwise')" \
    "$([ "$failed" -gt 0 ] && echo 'high' || echo 'default')" \
    "[$(view_action 'Branches' "$REPO_URL/branches"),$(view_action 'Pull requests' "$REPO_URL/pulls")]" \
    "" "" "$REPO_URL/branches"
}

# --------------------------- control channel -------------------------------

inbox_append() {
  [ -f "$INBOX" ] || printf '# Inbox — directives from the human\n\n' > "$INBOX"
  printf '\n- [ ] %s — %s\n' "$(date -Is)" "$1" >> "$INBOX"
}

start_control_listener() {
  (
    while :; do
      curl -s -N "$NTFY_URL/$CTRL_TOPIC/json" 2>/dev/null | while IFS= read -r line; do
        msg="$(printf '%s' "$line" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin); print(d.get("message","") if d.get("event")=="message" else "")
except Exception: print("")' 2>/dev/null)"
        [ -z "$msg" ] && continue
        case "$(printf '%s' "$msg" | tr '[:lower:]' '[:upper:]')" in
          PAUSE) touch "$PAUSEFILE"
            ntfy_publish "⏸ Pause queued" "$(progress_block)
Holding after the current run finishes. Send RESUME to continue." "pause_button" "default" "[$(ctrl_action Resume RESUME)]" ;;
          STOP) touch "$PAUSEFILE"
            [ -f "$CLAUDE_PIDFILE" ] && kill "$(cat "$CLAUDE_PIDFILE")" 2>/dev/null
            ntfy_publish "⏹ Run stopped" "$(progress_block)
Killed the current run and holding. Work is committed to its last checkpoint." "stop_button" "high" "[$(ctrl_action Resume RESUME)]" ;;
          RESUME) rm -f "$PAUSEFILE"
            ntfy_publish "▶️ Resuming" "$(progress_block)" "arrow_forward" "default" ;;
          STATUS)
            ntfy_publish "Lemely — status" "$(progress_block)
Run $(cat "$RUNFILE" 2>/dev/null || echo '?') · $([ -f "$PAUSEFILE" ] && echo '**PAUSED**' || echo 'running') · model \`$MODEL\`

**Recent commits**
$(recent_commits 3)" "information_source" "default" \
              "[$(view_action 'Latest commit' "$(commit_url)"),$(ctrl_action Pause PAUSE)]" "" "" "$(commit_url)" ;;
          SKIP)
            inbox_append "Skip the task you are currently stuck on: mark it [!] blocked in STATE.md, note it in BLOCKERS.md, and move to the next independent task."
            ntfy_publish "⏭ Skip filed" "$(progress_block)" "next_track_button" "default" ;;
          SYNC) ntfy_publish "🔄 Syncing…" "$(progress_block)
Pushing local branches to GitHub." "arrows_counterclockwise" "low" "" "lemely-sync"
            do_sync ;;
          SYNC\ *) ntfy_publish "🔄 Syncing…" "Pushing \`${msg#* }\` to GitHub." "arrows_counterclockwise" "low" "" "lemely-sync"
            do_sync "$(printf '%s' "$msg" | cut -d' ' -f2-)" ;;
          DIGEST) : > "$DIGESTFILE" ;;   # force a digest on the next beat
          *) inbox_append "$msg"
            ntfy_publish "📥 Directive filed" "\"$msg\"

$(progress_block)
The agent picks this up at its next checkpoint." "inbox_tray" "default" \
              "[$(view_action 'Open inbox' "$REPO_URL/blob/develop/BUILD/INBOX.md")]" "" "" "$REPO_URL/blob/develop/BUILD/INBOX.md" ;;
        esac
      done
      sleep 5
    done
  ) &
  CONTROL_PID=$!
}

# --------------------------- background monitor ----------------------------

start_monitor() {
  (
    last_sha=""; quiet_beats=0
    echo "$(date +%s)" > "$DIGESTFILE"
    while :; do
      sleep "$HEARTBEAT_SECS"
      run_no="$(cat "$RUNFILE" 2>/dev/null || echo '?')"
      started="$(cat "$STARTFILE" 2>/dev/null || date +%s)"
      elapsed=$(( ( $(date +%s) - started ) / 60 ))
      sha="$(git rev-parse --short HEAD 2>/dev/null)"

      ntfy_publish "Lemely — working" "$(progress_block)
Run **$run_no** · ${elapsed}m · model \`$MODEL\`

**Latest**
$(recent_commits 2)" "hourglass_flowing_sand" "low" \
        "[$(view_action 'Latest commit' "$(commit_url)"),$(ctrl_action Sync SYNC),$(ctrl_action Pause PAUSE)]" \
        "lemely-heartbeat" "" "$(commit_url)"

      # stall detection: no new commit across several beats
      if [ "$sha" = "$last_sha" ]; then
        quiet_beats=$((quiet_beats + 1))
        if [ "$quiet_beats" -eq "$STALL_BEATS" ]; then
          ntfy_publish "🐌 Possibly stalled" "$(progress_block)
No new commit for $(( STALL_BEATS * HEARTBEAT_SECS / 60 )) minutes. It may be on a long task, or stuck." \
            "snail" "default" "[$(ctrl_action 'Skip task' SKIP),$(ctrl_action Pause PAUSE),$(ctrl_action Status STATUS)]"
        fi
      else
        quiet_beats=0; last_sha="$sha"
      fi

      # daily digest
      last_digest="$(cat "$DIGESTFILE" 2>/dev/null || echo 0)"
      if [ $(( $(date +%s) - last_digest )) -ge "$DIGEST_SECS" ]; then
        date +%s > "$DIGESTFILE"
        {
          echo "# Lemely daily digest — $(date '+%Y-%m-%d %H:%M')"; echo
          progress_block; echo
          echo "## Commits (24h)"; git log --since='24 hours ago' --pretty='- `%h` %s' 2>/dev/null | head -60; echo
          echo "## Files changed (24h)"; git diff --stat "@{24 hours ago}" 2>/dev/null | tail -25; echo
          echo "## Open blockers"; sed -n '1,60p' BUILD/BLOCKERS.md 2>/dev/null || echo "none"; echo
          echo "## Screenshots captured"; find reports -name '*.png' 2>/dev/null | wc -l
        } > /tmp/lemely-digest.md
        ntfy_publish "📊 Daily digest" "$(progress_block)
$(git log --since='24 hours ago' --oneline 2>/dev/null | wc -l) commits in the last 24h. Full digest attached." \
          "bar_chart" "default" "[$(view_action 'Open repo' "$REPO_URL")]"
        ntfy_attach /tmp/lemely-digest.md "Daily digest $(date '+%d %b')" "bar_chart" "default"
      fi

      ntfy_publish "💀 Supervisor stopped responding" \
        "No heartbeat for ${WATCHDOG_MINUTES}m — the machine or the supervisor died." \
        "skull" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]" "lemely-watchdog" "${WATCHDOG_MINUTES}m"
    done
  ) &
  MONITOR_PID=$!
}

cleanup() {
  [ -n "${MONITOR_PID:-}" ] && kill "$MONITOR_PID" 2>/dev/null
  [ -n "${CONTROL_PID:-}" ] && kill "$CONTROL_PID" 2>/dev/null
  ntfy_cancel "lemely-watchdog"
}
trap cleanup EXIT INT TERM

# --------------------------- run loop --------------------------------------

FIRST_PROMPT="Read BUILD/MISSION.md end to end. It is your complete mission. Then read BUILD/STATE.md, docs/LEMELY_UI_SPEC.md and DESIGN.md, and begin execution exactly as MISSION.md instructs."
RESUME_PROMPT="You are resuming an unattended build. Read BUILD/INBOX.md FIRST and act on any unhandled directives, then BUILD/MISSION.md, BUILD/STATE.md, BUILD/DECISIONS.md and BUILD/BLOCKERS.md if present, and 'git log --oneline -15'. Clean up any dirty working tree with a wip commit, then continue from the first non-done task in STATE.md. Follow MISSION.md protocols exactly."

ntfy_publish "🚀 Supervisor started" "$(progress_block)
Host \`$(hostname)\` · model \`$MODEL\`

**Latest**
$(recent_commits 2)" "rocket" "default" \
  "[$(view_action 'Open repo' "$REPO_URL"),$(ctrl_action Status STATUS)]"

for f in "$REPORTMARK" "$SHOTMARK" "$BLOCKMARK"; do [ -f "$f" ] || touch "$f"; done
start_monitor
start_control_listener

run=0
while [ "$run" -lt "$MAX_RUNS" ]; do
  run=$((run + 1)); echo "$run" > "$RUNFILE"

  case "$(state_field status)" in
    COMPLETE)
      ntfy_publish "🎉 BUILD COMPLETE" "$(progress_block)
Finished after **$run** runs. \`DELIVERY.md\` is in the repo." "tada,white_check_mark" "urgent" \
        "[$(view_action 'Open DELIVERY.md' "$REPO_URL/blob/main/DELIVERY.md"),$(view_action 'Pull requests' "$REPO_URL/pulls")]" \
        "" "" "$REPO_URL/blob/main/DELIVERY.md"
      ntfy_attach "$REPO/DELIVERY.md" "DELIVERY.md" "page_facing_up" "default" "$REPO_URL/blob/main/DELIVERY.md"
      exit 0 ;;
    HALTED)
      ntfy_publish "🛑 Build HALTED" "$(progress_block)
Orchestrator halted the build. Blockers attached." "octagonal_sign" "urgent" \
        "[$(view_action 'Open blockers' "$REPO_URL/blob/develop/BUILD/BLOCKERS.md"),$(ctrl_action Resume RESUME)]"
      ntfy_attach "$REPO/BUILD/BLOCKERS.md" "BLOCKERS.md" "warning" "high"
      exit 1 ;;
  esac

  if [ -f "$PAUSEFILE" ]; then
    ntfy_publish "⏸ Paused" "$(progress_block)
Holding before run $run. Send RESUME, or delete BUILD/PAUSE." "pause_button" "default" \
      "[$(ctrl_action Resume RESUME),$(ctrl_action Status STATUS)]"
    do_sync                      # push everything before you take a look
    while [ -f "$PAUSEFILE" ]; do sleep 20; done
    ntfy_publish "▶️ Resumed" "$(progress_block)" "arrow_forward" "low"
  fi

  if [ "$run" -eq 1 ] && [ ! -f BUILD/JOURNAL.md ]; then PROMPT="$FIRST_PROMPT"; else PROMPT="$RESUME_PROMPT"; fi

  LOG="$LOGDIR/run-$(printf '%04d' "$run")-$(date +%Y%m%d-%H%M%S).log"
  date +%s > "$STARTFILE"
  RUNSTART_SHA="$(git rev-parse HEAD 2>/dev/null)"
  echo "=== run $run starting $(date -Is) model=$MODEL ===" | tee -a "$LOG"

  claude -p "$PROMPT" --model "$MODEL" \
    --dangerously-skip-permissions --verbose >>"$LOG" 2>&1 &
  CLAUDE_PID=$!; echo "$CLAUDE_PID" > "$CLAUDE_PIDFILE"
  wait "$CLAUDE_PID"; rc=$?; rm -f "$CLAUDE_PIDFILE"

  echo "=== run $run exited rc=$rc $(date -Is) ===" >>"$LOG"
  mins=$(( ( $(date +%s) - $(cat "$STARTFILE") ) / 60 ))
  DIFFSUM="$(run_diff_summary "$RUNSTART_SHA")"

  # --- phase transition -------------------------------------------------
  phase_now="$(state_field current_phase)"; phase_prev="$(cat "$PHASEFILE" 2>/dev/null || echo '')"
  if [ -n "$phase_now" ] && [ "$phase_now" != "$phase_prev" ]; then
    echo "$phase_now" > "$PHASEFILE"
    if [ -n "$phase_prev" ]; then
      ntfy_publish "✅ Phase $phase_prev complete — $(phase_name "$phase_prev")" "$(progress_block)
Now starting **Phase $phase_now — $(phase_name "$phase_now")**.

$DIFFSUM" "white_check_mark" "high" \
        "[$(view_action 'Review PRs' "$REPO_URL/pulls"),$(view_action 'Phase report' "$REPO_URL/tree/develop/reports/phase-$phase_prev")]" \
        "" "" "$REPO_URL/pulls"
    fi
  fi

  # --- new milestone reports & contact sheets ---------------------------
  while IFS= read -r rpt; do
    [ -n "$rpt" ] && ntfy_attach "$rpt" "📄 $(dirname "${rpt#./}")" "clipboard" "high" \
      "$REPO_URL/blob/develop/${rpt#./}"
  done < <(find reports -name 'REPORT.md' -o -name 'contact-sheet.html' 2>/dev/null | while read -r f; do [ "$f" -nt "$REPORTMARK" ] && echo "$f"; done)
  touch "$REPORTMARK"

  # --- newest screenshots (visual proof of UI progress) -----------------
  shots="$(find reports -name '*.png' 2>/dev/null | while read -r f; do [ "$f" -nt "$SHOTMARK" ] && echo "$f"; done | head -"$MAX_NEW_SHOTS")"
  if [ -n "$shots" ]; then
    total_new="$(find reports -name '*.png' 2>/dev/null | while read -r f; do [ "$f" -nt "$SHOTMARK" ] && echo x; done | wc -l)"
    ntfy_publish "🖼 $total_new new screenshot(s)" "$(progress_block)
Newest attached below." "framed_picture" "low" "[$(view_action 'All screenshots' "$REPO_URL/tree/develop/reports")]"
    while IFS= read -r shot; do
      [ -n "$shot" ] && ntfy_attach "$shot" "$(basename "$(dirname "$shot")")/$(basename "$shot")" "framed_picture" "low"
    done <<< "$shots"
  fi
  touch "$SHOTMARK"

  # --- new blockers ------------------------------------------------------
  if [ -f BUILD/BLOCKERS.md ] && [ BUILD/BLOCKERS.md -nt "$BLOCKMARK" ]; then
    ntfy_publish "⚠️ New blocker recorded" "$(progress_block)
The agent hit something it couldn't resolve and moved on. Details attached." "warning" "high" \
      "[$(view_action 'Open blockers' "$REPO_URL/blob/develop/BUILD/BLOCKERS.md"),$(ctrl_action 'Send guidance' 'STATUS')]"
    ntfy_attach BUILD/BLOCKERS.md "BLOCKERS.md" "warning" "high"
    touch "$BLOCKMARK"
  fi

  # --- outcome -----------------------------------------------------------
  if tail -n 80 "$LOG" | grep -qiE "usage limit|rate limit|limit reached|overloaded|429"; then
    wait_secs="$(parse_reset_seconds "$LOG")"
    if [ -n "$wait_secs" ]; then wait_secs=$((wait_secs + LIMIT_RESUME_MARGIN)); precision="from the limit message"
    else wait_secs="$BACKOFF_LIMIT_FALLBACK"; precision="estimated — no reset time given"; fi

    if [ "$wait_secs" -gt "$MAX_LIMIT_WAIT" ]; then
      ntfy_publish "🛑 Long limit window — stopping" "$(progress_block)
Reset is ~$((wait_secs / 3600))h away (likely the weekly cap). Stopping cleanly; nothing is lost.
Rerun \`./supervisor.sh\` after the reset.

$DIFFSUM" "octagonal_sign" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]"
      exit 0
    fi

    if should_notify_failure "$LOG"; then
      ntfy_publish "⏳ Usage limit — waiting" "$(progress_block)
Resuming in **$((wait_secs / 60))m** (~$(date -d "+$wait_secs seconds" '+%H:%M')), $precision.
Ran ${mins}m before hitting the wall.

$DIFFSUM" "hourglass_flowing_sand" "low" "[$(ctrl_action Status STATUS)]" "lemely-limit"
    fi
    sleep "$wait_secs"
    ntfy_publish "▶️ Limit reset — resuming" "$(progress_block)" "arrow_forward" "low" "" "lemely-limit"

  elif [ "$rc" -ne 0 ]; then
    if should_notify_failure "$LOG"; then
      ntfy_publish "⚠️ Run $run crashed (rc=$rc)" "$(progress_block)
Ran ${mins}m · retrying in $((BACKOFF_CRASH / 60))m · log attached.

$DIFFSUM" "warning" "high" \
        "[$(ctrl_action 'Skip task' SKIP),$(ctrl_action Pause PAUSE),$(view_action 'Open repo' "$REPO_URL")]"
      ntfy_attach "$LOG" "Crash log — run $run (rc=$rc)" "page_facing_up" "high"
    fi
    sleep "$BACKOFF_CRASH"

  else
    ntfy_publish "🔄 Run $run checkpointed" "$(progress_block)
${mins}m · restarting with fresh context.

$DIFFSUM" "recycle" "min" "[$(view_action 'Latest commit' "$(commit_url)")]" "lemely-checkpoint" "" "$(commit_url)"
    sleep 20
  fi
done

ntfy_publish "🛑 MAX_RUNS=$MAX_RUNS reached" "$(progress_block)
Safety valve tripped." "octagonal_sign" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]"
exit 1
