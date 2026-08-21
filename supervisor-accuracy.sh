#!/usr/bin/env bash
# Lemely unattended ACCURACY-PROGRAMME supervisor.
#
# Sibling of supervisor.sh (the redesign supervisor). Independent script,
# independent ntfy topics, and it runs in the dedicated accuracy worktree at
# /home/sico/Lemely-worktrees/accuracy — never in /home/sico/Lemely itself.
# supervisor.sh is untouched by this file and must never run at the same time.
#
# RUN THIS FROM THE MAIN CHECKOUT, NEVER FROM THE WORKTREE IT DRIVES.
#
# The script's HOME is /home/sico/Lemely (the main checkout). Its cwd at runtime
# must be /home/sico/Lemely-worktrees/accuracy (the worktree). Those are two
# different things and the split is the whole point:
#
#   - It used to be launched as ./supervisor-accuracy.sh from inside the
#     worktree, so the live supervisor was whatever version the checked-out
#     feature branch happened to carry. On 2026-08-19 that cost a night: the
#     background-wait hardening below was committed to
#     chore/accuracy-orchestration-and-decisions, the worktree was sitting on
#     the #56 feature branch, and the supervisor ran the unfixed script for five
#     more runs. Operator infrastructure must not be versioned by the branch it
#     operates on — and the worktree's branch changes on every issue.
#   - The fix for that is NOT to leave git. A copy outside the repo has no
#     history, no diff and no backup, and silently forks from the tracked one.
#     The main checkout gives both properties at once: under version control,
#     and not on the branch being churned.
#
# Residual risk, stated rather than hidden: /home/sico/Lemely is still a
# checkout someone can switch branches on. That is far less likely than the
# worktree, but it is the same trap in miniature — if you switch it, check this
# file before relaunching.
#
# Run inside tmux — note the -c: cwd is the worktree, the script is not.
#   tmux new -s lemely-acc -c /home/sico/Lemely-worktrees/accuracy \
#     /home/sico/Lemely/supervisor-accuracy.sh
# Operator's manual: CONTROLS-ACCURACY.md
#
# Stops when the GitHub board reports every non-H M0/M1/M2 leaf Done, or when
# BUILD/ACCURACY-STATE.md gains "status: COMPLETE" (no such field exists today;
# honoured if the contract ever adds one), or after MAX_RUNS.

set -u

# --------------------------- configuration ---------------------------------
REPO="/home/sico/Lemely-worktrees/accuracy"   # the accuracy worktree, NOT the main repo
MAIN_REPO="/home/sico/Lemely"
NTFY_TOPIC="lemely-acc-EF5H6SKKGxyJseM"
CTRL_TOPIC="lemely-acc-ctl-bqlsqcY9FfbfQd"    # you PUBLISH here to steer the run
# ONE base URL, used by ntfy_publish, ntfy_attach, the control listener AND
# nudge-accuracy. (supervisor.sh publishes to :7532 while nudge posts to port
# 80 — that inconsistency is deliberately not reproduced here.)
NTFY_URL="http://home-server:7532"
REPO_URL="https://github.com/LemelyIG/Lemely"

# KNOWN LIMITATION (documented here, not fixed in production code):
# lemely/runtime/notify.py hardcodes _NTFY_BASE = "http://home-server" (i.e.
# port 80, not our :7532) and no-ops entirely unless LEMELY_NTFY_TOPIC is set.
# Exporting the topic below is the most this supervisor can do for it —
# budget_notify() and any other Python caller will at least stop being a
# silent no-op — but a Python-side notification still targets port 80, which
# nothing is listening on here. scripts/accuracy_notify.sh (bash, port :7532,
# same topic) is the reliable path; direct agents there, not through Python.
export LEMELY_NTFY_TOPIC="$NTFY_TOPIC"

# Background-task wait ceiling for 'claude -p'. The default is 600s: a run that
# dispatches the pytest suite or an accuracy-* workflow to the background and
# waits on it is TERMINATED at ten minutes — and terminated with rc=0, so this
# supervisor read it as a clean checkpoint and restarted with fresh context.
# Runs 1-8 of 2026-08-19 did exactly that: 7 of 9 logs end in "Background tasks
# still running after 600s; terminating", producing eight 'wip checkpoint'
# commits and no landed work, because each fresh run re-armed the same wait.
#
# Bounded, NOT 0. Nothing in this supervisor kills a running 'claude -p' on a
# timer — WATCHDOG_MINUTES is a notify-only dead-man's switch for the machine
# or supervisor dying, and the heartbeat refreshes it regardless of what the
# agent is doing. So this ceiling IS the only bound on a wedged run; 0 would
# remove it entirely. 2.5h covers the full pytest suite, an accuracy-review
# workflow, and a long accuracy-measure sweep with room to spare.
#
# A wait this long crosses STALL_BEATS (3 beats = 30 min with no commit), so a
# legitimate long wait emits stall notices — that notice already reads "may be
# on a long measurement sweep, or stuck". When the ceiling IS hit, the run is
# terminated with rc=0 and looks identical to a clean finish, so the outcome
# block below detects it explicitly and hands the fact to the next run rather
# than letting it silently re-arm the same doomed wait.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=$(( 150 * 60 * 1000 ))   # 2.5 hours

MODEL="opus"                    # orchestrator model — Opus decides, Sonnet subagents work

COST_CEILING_USD="25.00"        # lemely.toml total_usd_ceiling (pre-flight check, not a hard stop)
REVIEW_BUDGET_PCT="10"          # the review-rate budget the ratchet drives toward
SPEND_MARK_50="12.50"           # notify once when ledger spend crosses these
SPEND_MARK_80="20.00"

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
ATTACH_MAX_BYTES=1900000        # stay under ntfy's 2MB attachment cap
BOARD_TTL=300                   # seconds to cache 'accuracy_board.py status --json'
GATES_TIMEOUT=1800              # cap on a GATES keyword run of scripts/check.sh
GATE_SUITE_TIMEOUT=7200         # cap on the between-runs gate sweep (gate_sweep).
                                # Deliberately far looser than GATES_TIMEOUT: the
                                # sweep costs wall-clock, not tokens, and a sweep
                                # that gets cut off short reintroduces the exact
                                # "the suite never finishes" failure it exists to
                                # end. Only tighten this against a measured suite
                                # duration, never against a guess.
MAX_RESUME_CHAIN=6              # consecutive '--resume' runs before a forced cold
                                # start. SET THIS TO 0 TO DISABLE RESUMING ENTIRELY
                                # (0 means the chain is always already at the cap,
                                # so every run starts cold) — that is the kill
                                # switch if resumed runs misbehave.
                                #
                                # Resuming skips re-orientation, but it is not a
                                # free win and the honest accounting is: a resumed
                                # run re-sends the whole accumulated conversation as
                                # a cold cache write, because the prompt cache TTL
                                # is ~5 min and runs are 10-40 min apart. So each
                                # resume trades a bigger input for skipped
                                # re-reading. Measured over the 14 runs of
                                # 2026-08-19 the re-reading it saves was small
                                # (57 Read calls, 1.1 min of tool time total), so
                                # expect a modest gain, not a transformation.
                                # Six is a guess at where a growing transcript
                                # starts costing more in in-session compaction than
                                # a cold start would; lower it if runs begin
                                # compacting mid-work, raise it if they never do.

LOGDIR="$REPO/BUILD/logs"
STATEDIR="$LOGDIR/.acc-supervisor"    # runtime state; BUILD/logs/ is gitignored,
                                      # so the auto-committing orchestrator never picks it up
STATEMD="$REPO/BUILD/ACCURACY-STATE.md"
MISSION="$REPO/BUILD/ACCURACY-MISSION.md"
INBOX="$REPO/BUILD/ACCURACY-INBOX.md"
PAUSEFILE="$REPO/BUILD/PAUSE"         # gitignored by exact name; different worktree, so no
                                      # collision with the redesign supervisor's PAUSE
NOTIFY_STATE="$STATEDIR/notify_state"
RUNFILE="$STATEDIR/run"
MILESTONEFILE="$STATEDIR/milestones_done"
BLOCKMARK="$STATEDIR/blockmark"
STARTFILE="$STATEDIR/start"
DIGESTFILE="$STATEDIR/digest"
CLAUDE_PIDFILE="$STATEDIR/claude_pid"
BOARD_CACHE="$STATEDIR/board.json"
PRS_SEEN="$STATEDIR/prs_seen"
H_SEEN="$STATEDIR/h_blocking_seen"
CI_RED_SEEN="$STATEDIR/ci_red_seen"    # dedup key: "<pr>:<head-sha>"
SPEND_MARK="$STATEDIR/spend_mark"
NRMARK="$STATEDIR/not_reportable_sig"
TIMEOUTFILE="$STATEDIR/last_timeout"   # handoff: a run killed by the background-task
                                       # wait ceiling leaves its story here for the next
                                       # run's prompt. Consumed and deleted when read.
GATEREPORT="$STATEDIR/gate_report"     # handoff: the out-of-session gate sweep's verdict.
GATE_SHA="$STATEDIR/gate_sha"          # the sha that verdict covers…
GATE_DIRTY="$STATEDIR/gate_dirty"      # …and how many files were uncommitted under it.
                                       # Unlike TIMEOUTFILE these are NOT consumed on
                                       # read: the verdict stays valid until the tree
                                       # moves, and every run should see it.
SESSIONFILE="$STATEDIR/session_id"     # the Claude session runs continue into…
RESUME_CHAINFILE="$STATEDIR/resume_chain"   # …and how many consecutive resumes it
                                       # has carried. Both are advisory: losing them
                                       # costs one cold start, never correctness.

# --------------------------- ntfy helpers ----------------------------------

# ntfy_publish TITLE MESSAGE TAGS PRIORITY [ACTIONS_JSON] [SEQUENCE_ID] [DELAY] [CLICK_URL]
# The ntfy server has been observed refusing connections (it was down when this
# was written): every path in here swallows every exception and never blocks.
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
  # SAFETY — NEVER RELAX THIS GUARD: tests/fixtures/real-papers/ contains a
  # minor's real handwritten exam scripts. They were committed to the repo only
  # after deliberate human sign-off (H10 / issue #60) and must never leave it:
  # never attach them to a notification, never redistribute them anywhere.
  case "$file" in *tests/fixtures/real-papers/*) return 0 ;; esac
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

# --------------------------- startup guards --------------------------------

die() { echo "supervisor-accuracy: $1" >&2; ntfy_publish "🛑 Accuracy supervisor refused to start" "$1" "octagonal_sign" "high"; exit 1; }

# Guard 1: the accuracy worktree must exist and BE a worktree (worktrees carry
# a .git *file* pointing back at the main repo, not a .git directory).
if [ ! -d "$REPO" ] || [ ! -f "$REPO/.git" ] || ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  cat >&2 <<EOF
supervisor-accuracy: $REPO is missing or is not a git worktree.
Bootstrap it first (ACCURACY-MISSION.md section 5):

  git -C /home/sico/Lemely worktree add /home/sico/Lemely-worktrees/accuracy develop
  cd /home/sico/Lemely-worktrees/accuracy
  python -m venv .venv
  .venv/bin/pip install -e ".[dev,ui,web,db]"

Then export GEMINI_API_KEY, run '.venv/bin/lemely doctor', and relaunch.
EOF
  exit 1
fi

# Guard 2: the worktree needs its OWN venv — the main .venv editable-installs
# lemely from /home/sico/Lemely, so imports would silently resolve to whatever
# branch the main tree has checked out.
if [ ! -x "$REPO/.venv/bin/python" ]; then
  cat >&2 <<EOF
supervisor-accuracy: $REPO has no venv at .venv/bin/python.
Bootstrap it (the worktree must NOT reuse /home/sico/Lemely/.venv):

  cd /home/sico/Lemely-worktrees/accuracy
  python -m venv .venv
  .venv/bin/pip install -e ".[dev,ui,web,db]"
EOF
  exit 1
fi
PY="$REPO/.venv/bin/python"

# Guard 3: every accuracy-programme artifact must be present in the worktree.
# They all start life untracked in /home/sico/Lemely; until every one of them
# is committed and pushed to develop, a fresh worktree simply does not
# contain them — this is the single most common first-run failure, so name
# every missing path rather than stopping at the first one.
MISSING=""
for f in \
  "$MISSION" "$STATEMD" "$INBOX" \
  "$REPO/scripts/accuracy_board.py" "$REPO/scripts/accuracy_notify.sh" \
  "$REPO/.claude/workflows/accuracy-issue-execute.js" \
  "$REPO/.claude/workflows/accuracy-review.js" \
  "$REPO/.claude/workflows/accuracy-measure.js" \
  "$REPO/.claude/workflows/accuracy-label-batch.js" \
  "$REPO/.claude/workflows/accuracy-gate-triage.js" \
  "$REPO/.claude/workflows/accuracy-pr-land.js" \
  "$REPO/.claude/agents/accuracy-implementer.md" \
  "$REPO/.claude/agents/accuracy-reviewer.md" \
  "$REPO/.claude/agents/accuracy-measurer.md" \
  "$REPO/.claude/agents/accuracy-labeller.md" \
  "$REPO/.claude/agents/accuracy-scribe.md" \
; do
  [ -f "$f" ] || MISSING="$MISSING
  - $f"
done
if [ -n "$MISSING" ]; then
  die "the worktree at $REPO is missing these artifacts:$MISSING

Likely cause: the accuracy-programme setup (BUILD/ACCURACY-*.md, scripts/accuracy_board.py,
scripts/accuracy_notify.sh, the six .claude/workflows/accuracy-*.js and the five
.claude/agents/accuracy-*.md) was never committed and pushed to develop, so this worktree —
checked out from develop — does not have it. Commit and push it from /home/sico/Lemely, then
fast-forward and re-fetch the worktree, before relaunching."
fi

# Guard 4: the redesign supervisor must not be running. Two unattended agents
# on one repo race on commits and pushes. ('supervisor.sh' does not match this
# script's own name, supervisor-accuracy.sh.)
if pgrep -f 'supervisor\.sh' >/dev/null 2>&1; then
  die "the redesign supervisor (supervisor.sh) is running — stop it first: pgrep -af 'supervisor\\.sh'"
fi

cd "$REPO" || exit 1
mkdir -p "$LOGDIR" "$STATEDIR"

[ -z "${GEMINI_API_KEY:-}" ] && echo "supervisor-accuracy: WARNING — GEMINI_API_KEY is not exported; Gemini-touching work will fail 'lemely doctor'." >&2

# Guard 5 (precondition, checked before the first run): origin/develop must
# contain origin/main. accuracy-issue-execute cuts feature branches from
# origin/develop, so the PUSHED pair is the one that governs — a local-only
# develop..main comparison can read 0 while the pushed refs still diverge (or
# vice versa). Fast-forwarding and pushing develop is a HUMAN launch-checklist
# item, never something this script does silently.
git -C "$REPO" fetch --quiet origin
BEHIND="$(git -C "$REPO" rev-list --count origin/develop..origin/main 2>/dev/null || echo unknown)"
if [ "$BEHIND" != "0" ]; then
  MSG="origin/develop is $BEHIND commit(s) behind origin/main, so feature branches cut from origin/develop would lack the spec and the corpus. Fast-forward and PUSH it yourself, then relaunch:

  git -C /home/sico/Lemely push origin main:develop"
  echo "supervisor-accuracy: REFUSING TO START — $MSG" >&2
  ntfy_publish "🛑 develop is behind main — not starting" "$MSG" "octagonal_sign" "high" \
    "[$(view_action 'Compare' "$REPO_URL/compare/develop...main")]" "" "" "$REPO_URL/compare/develop...main"
  exit 1
fi

# --------------------------- state & progress ------------------------------

# BUILD/ACCURACY-STATE.md keeps a thin 'key: value' header (its own documented
# contract); GitHub — read through scripts/accuracy_board.py — is the tracker.
state_field() { grep -m1 "^$1:" "$STATEMD" 2>/dev/null | sed "s/^$1:[[:space:]]*//"; }

# board_json — cached 'accuracy_board.py status --json'. Serves a stale cache,
# then nothing, when gh or the network is down; callers must tolerate failure.
board_json() {
  local now
  now="$(date +%s)"
  if [ -f "$BOARD_CACHE" ] && [ $(( now - $(stat -c %Y "$BOARD_CACHE" 2>/dev/null || echo 0) )) -lt "$BOARD_TTL" ]; then
    cat "$BOARD_CACHE"; return 0
  fi
  local out
  if out="$(cd "$REPO" && timeout 45 "$PY" scripts/accuracy_board.py status --json 2>/dev/null)" && [ -n "$out" ]; then
    printf '%s' "$out" > "$BOARD_CACHE"; printf '%s' "$out"; return 0
  fi
  [ -f "$BOARD_CACHE" ] && { cat "$BOARD_CACHE"; return 0; }
  return 1
}

progress_block() {   # the standard, information-dense body prefix
  local json review spend
  if json="$(board_json)"; then
    printf '%s' "$json" | python3 -c 'import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for m in ("M0", "M1", "M2", "M3", "M4"):
    row = d.get("milestone_counts", {}).get(m)
    if not row:
        continue
    total = sum(row.values())
    done = row.get("Done", 0)
    pct = int(done * 100 / total) if total else 0
    bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
    print(f"**{m}** `{bar}` {done}/{total}")
for i in d.get("in_progress", [])[:2]:
    num = i.get("number")
    st = i.get("status")
    title = str(i.get("title", ""))[:64]
    print(f"▸ #{num} [{st}] {title}")
blocked = d.get("blocked", [])
if blocked:
    print(f"⚠ {len(blocked)} issue(s) blocked")
h = d.get("h_open", [])
if h:
    nums = ["#" + str(x.get("number")) for x in h]
    print("✋ open H (human-only): " + ", ".join(nums))' 2>/dev/null
  else
    printf '**Board unreachable — local state only**\n'
    printf '▸ branch: %s · doing: %s\n' "$(state_field branch)" "$(state_field in_the_middle_of)"
  fi
  review="$(state_field review_rate)"
  spend="$(state_field spend_usd)"
  [ -n "$review" ] && printf '· review rate: %s against the %s%% budget\n' "$review" "$REVIEW_BUDGET_PCT"
  [ -n "$spend" ] && printf '· Gemini spend: $%s of $%s (ledger figure — understated 2-4x until M0.2 lands)\n' "$spend" "$COST_CEILING_USD"
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

# --------------------------- programme-specific checks ---------------------

# Any PR opened against develop is worth a phone buzz: a merge to develop is
# the programme's unit of shipped work.
check_new_prs() {
  command -v gh >/dev/null 2>&1 || return 0
  local out
  out="$(cd "$REPO" && timeout 30 gh pr list --base develop --state open --json number,title,url 2>/dev/null)" || return 0
  [ -n "$out" ] || return 0
  touch "$PRS_SEEN"
  printf '%s' "$out" | python3 -c 'import json,sys
try:
    for p in json.load(sys.stdin): print(p["number"], p["url"], p["title"])
except Exception: pass' 2>/dev/null | while read -r num url title; do
    grep -qx "$num" "$PRS_SEEN" 2>/dev/null && continue
    echo "$num" >> "$PRS_SEEN"
    ntfy_publish "🔀 PR #$num opened to develop" "$(progress_block)
**$title**
$url" "arrows_counterclockwise" "high" \
      "[$(view_action 'Open PR' "$url"),$(view_action 'All PRs' "$REPO_URL/pulls")]" "" "" "$url"
  done
}

# check_ci_status — S3: nothing else watches GitHub Actions once a PR is
# open. check_new_prs only notices the PR appearing; without this, a red run
# sits forever with no notification and no triage. For every open PR into
# develop, read 'gh pr checks' and notify ONCE per (PR, head sha) when it
# turns red — dedup by CI_RED_SEEN, in the style of PRS_SEEN/H_SEEN above.
# Never re-notifies for the same PR+sha (a later push gets a fresh sha and so
# a fresh chance to notify); accuracy-pr-land is the one that actually routes
# a red run into accuracy-gate-triage — this is only the human-facing buzz.
check_ci_status() {
  command -v gh >/dev/null 2>&1 || return 0
  local out
  out="$(cd "$REPO" && timeout 30 gh pr list --base develop --state open --json number,url,headRefOid 2>/dev/null)" || return 0
  [ -n "$out" ] || return 0
  touch "$CI_RED_SEEN"
  printf '%s' "$out" | python3 -c 'import json,sys
try:
    for p in json.load(sys.stdin): print(p["number"], p["headRefOid"], p["url"])
except Exception: pass' 2>/dev/null | while read -r num sha url; do
    key="$num:$sha"
    grep -qx "$key" "$CI_RED_SEEN" 2>/dev/null && continue
    checks="$(cd "$REPO" && timeout 30 gh pr checks "$num" --json bucket,name,link 2>/dev/null)"
    [ -n "$checks" ] || continue
    bucket="$(printf '%s' "$checks" | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
print("fail" if any(c.get("bucket") == "fail" for c in d) else "other")' 2>/dev/null)"
    [ "$bucket" = "fail" ] || continue
    echo "$key" >> "$CI_RED_SEEN"
    failing="$(printf '%s' "$checks" | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for c in d:
    if c.get("bucket") == "fail": print("· " + str(c.get("name", "?")))' 2>/dev/null | head -5)"
    ntfy_publish "🔴 CI red on PR #$num" "$(progress_block)
$failing

The agent's accuracy-pr-land run routes this into accuracy-gate-triage on its own — this is a
heads-up, not a call to action, unless it stays red across several beats." "x" "high" \
      "[$(view_action 'Open PR' "$url"),$(view_action 'Checks' "$url/checks")]" "" "" "$url/checks"
  done
}

# An H-numbered issue turning up as the blocker of an open board item means
# only the human can unblock — urgent, once per (blocked, H) pair.
check_h_blocking() {
  local json pairs line
  json="$(board_json)" || return 0
  pairs="$(printf '%s' "$json" | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
h = {x.get("number") for x in d.get("h_open", [])}
for b in d.get("blocked", []):
    for dep in sorted(set(b.get("blocked_by", [])) & h):
        print(str(b.get("number")) + ":" + str(dep))' 2>/dev/null)"
  [ -n "$pairs" ] || return 0
  touch "$H_SEEN"
  for line in $pairs; do
    grep -qx "$line" "$H_SEEN" 2>/dev/null && continue
    echo "$line" >> "$H_SEEN"
    ntfy_publish "✋ H issue #${line#*:} now blocks #${line%%:*}" "$(progress_block)
Issue #${line%%:*} is waiting on human task #${line#*:}. Only you can unblock it — the agent will not touch, close, or work around an H issue." \
      "raised_hand" "urgent" \
      "[$(view_action 'Open H issue' "$REPO_URL/issues/${line#*:}"),$(view_action 'Blocked issue' "$REPO_URL/issues/${line%%:*}")]" \
      "" "" "$REPO_URL/issues/${line#*:}"
  done
}

# Ledger spend crossing 50% / 80% of total_usd_ceiling — once each. The
# ceiling itself is a PRE-FLIGHT check in the pipeline, not a hard stop: one
# request can still overshoot, which is exactly why these marks exist.
check_spend() {
  local spend level prev
  spend="$(state_field spend_usd | tr -dc '0-9.')"
  [ -n "$spend" ] || return 0
  level="$(python3 -c "
import sys
try: s = float(sys.argv[1])
except Exception: s = 0.0
print(80 if s >= float(sys.argv[2]) else (50 if s >= float(sys.argv[3]) else 0))" "$spend" "$SPEND_MARK_80" "$SPEND_MARK_50" 2>/dev/null || echo 0)"
  prev="$(cat "$SPEND_MARK" 2>/dev/null || echo 0)"
  if [ "${level:-0}" -gt "${prev:-0}" ] 2>/dev/null; then
    echo "$level" > "$SPEND_MARK"
    ntfy_publish "💸 Gemini spend crossed ${level}% of ceiling" "$(progress_block)
Ledger reads \$$spend of \$$COST_CEILING_USD. Remember: the ledger understates real spend 2-4x until M0.2's pricing fix lands, and the ceiling is a pre-flight check, not a hard stop." \
      "money_with_wings" "$([ "$level" = "80" ] && echo urgent || echo high)" \
      "[$(ctrl_action Budget BUDGET),$(ctrl_action Pause PAUSE)]"
  fi
}

# A measurement result adjudicated NOT REPORTABLE (below the A/A floor, under
# an n-floor, or pre-instrument) — the orchestrator writes that literal token.
check_not_reportable() {
  local log="$1" hits sig prev
  hits="$( { grep -h "NOT REPORTABLE" "$log" "$STATEMD" 2>/dev/null || true; } | strip_ansi | head -10)"
  [ -n "$hits" ] || return 0
  sig="$(printf '%s' "$hits" | sha256sum | cut -d' ' -f1)"
  prev="$(cat "$NRMARK" 2>/dev/null || echo '')"
  [ "$sig" = "$prev" ] && return 0
  echo "$sig" > "$NRMARK"
  ntfy_publish "🚫 Result adjudicated NOT REPORTABLE" "$(progress_block)
$hits

A number below the A/A churn floor or an n-floor is noise and stays unpublished. This is the instrument working, not a failure." \
    "no_entry_sign" "high" "[$(view_action 'Decisions' "$REPO_URL/blob/develop/BUILD/DECISIONS.md")]"
}

# Milestone-epic completion, derived from the board (epics #24 M0 · #35 M1 ·
# #43 M2 · #53 M3 · #54 M4). Replaces the redesign supervisor's STATE.md
# phase-transition notice.
milestones_done() {
  board_json | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
print(",".join(sorted(e.get("milestone","") for e in d.get("epics",[]) if e.get("status") == "Done")))' 2>/dev/null
}

check_milestone_transition() {
  local now prev
  board_json >/dev/null 2>&1 || return 0   # board unreachable: don't fake a transition
  now="$(milestones_done)"
  [ -f "$MILESTONEFILE" ] || { printf '%s' "$now" > "$MILESTONEFILE"; return 0; }
  prev="$(cat "$MILESTONEFILE")"
  [ "$now" = "$prev" ] && return 0
  printf '%s' "$now" > "$MILESTONEFILE"
  ntfy_publish "✅ Milestone complete — board now shows [$now] Done" "$(progress_block)
Was [$prev].

$(run_diff_summary "${RUNSTART_SHA:-}")" "white_check_mark" "high" \
    "[$(view_action 'Review PRs' "$REPO_URL/pulls"),$(view_action 'Board' 'https://github.com/orgs/LemelyIG/projects/1')]" \
    "" "" "$REPO_URL/pulls"
}

# The programme's own completion test: every non-H M0/M1/M2 leaf Done on the
# board. M3/M4 are deliberately unscoped — stopping here is the mission's
# stop-and-ask rule number 8, not an error.
board_complete() {
  board_json | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(1)
c = d.get("milestone_counts", {})
for m in ("M0", "M1", "M2"):
    row = c.get(m)
    if not row or sum(row.values()) == 0 or sum(row.values()) != row.get("Done", 0):
        sys.exit(1)
sys.exit(0)' 2>/dev/null
}

# --------------------------- control channel -------------------------------

inbox_append() {
  [ -f "$INBOX" ] || printf '# ACCURACY-INBOX.md — steering inbox for the accuracy programme\n\n' > "$INBOX"
  printf '\n- [ ] %s — %s\n' "$(date -Is)" "$1" >> "$INBOX"
}

run_gates() {   # background worker for the GATES keyword
  local glog rc
  glog="$LOGDIR/gates-$(date +%Y%m%d-%H%M%S).log"
  # </dev/null: run_gates is backgrounded ('run_gates &') from inside the
  # control listener's `while read -r line` loop, which is itself fed by a
  # `curl -N ... | while ...` pipe. Without redirecting stdin here, the
  # backgrounded scripts/check.sh subprocess would inherit that same pipe fd
  # and could steal bytes meant for the control-channel reader while GATES
  # runs (up to GATES_TIMEOUT), silently dropping PAUSE/STOP/etc.
  ( cd "$REPO" && timeout "$GATES_TIMEOUT" bash scripts/check.sh ) </dev/null >"$glog" 2>&1
  rc=$?
  ntfy_publish "$([ "$rc" -eq 0 ] && echo '✅ Gates PASS' || echo "❌ Gates FAIL (rc=$rc)")" \
    "$(progress_block)
\`\`\`
$(strip_ansi < "$glog" | tail -n 25)
\`\`\`" \
    "$([ "$rc" -eq 0 ] && echo 'white_check_mark' || echo 'x')" \
    "$([ "$rc" -eq 0 ] && echo 'default' || echo 'high')"
}

# file_directive MSG — the fallback for anything that isn't a recognised
# keyword (bare, or keyword + exactly one argument): file it verbatim in the
# inbox rather than mis-parsing it as a command. Shared by the catch-all case
# arm and by SYNC/ISSUE when they're handed more than one argument (e.g. "sync
# the fixtures before measuring" must land here, not in do_sync with target
# "the").
file_directive() {
  inbox_append "$1"
  ntfy_publish "📥 Directive filed" "\"$1\"

$(progress_block)
The agent picks this up at its next checkpoint." "inbox_tray" "default" \
    "[$(view_action 'Open inbox' "$REPO_URL/blob/develop/BUILD/ACCURACY-INBOX.md")]" "" "" "$REPO_URL/blob/develop/BUILD/ACCURACY-INBOX.md"
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
            ntfy_publish "Accuracy — status" "$(progress_block)
Run $(cat "$RUNFILE" 2>/dev/null || echo '?') · $([ -f "$PAUSEFILE" ] && echo '**PAUSED**' || echo 'running') · model \`$MODEL\`

**Recent commits**
$(recent_commits 3)" "information_source" "default" \
              "[$(view_action 'Latest commit' "$(commit_url)"),$(ctrl_action Pause PAUSE)]" "" "" "$(commit_url)" ;;
          SKIP)
            inbox_append "Skip the issue you are currently stuck on: move it back with 'accuracy_board.py block <n> --on <issue-or-reason>', record the blocker, and take the next issue from 'accuracy_board.py next'."
            ntfy_publish "⏭ Skip filed" "$(progress_block)" "next_track_button" "default" ;;
          SYNC) ntfy_publish "🔄 Syncing…" "$(progress_block)
Pushing local branches to GitHub." "arrows_counterclockwise" "low" "" "lemely-acc-sync"
            do_sync ;;
          SYNC\ *)
            # Only "SYNC <one-branch-name>" is a command — a keyword plus a
            # SECOND word means this is free text that happens to start with
            # "sync" ("sync the fixtures before measuring"), not a directive
            # to sync one branch called "the".
            arg="$(printf '%s' "$msg" | cut -d' ' -f2-)"
            if printf '%s' "$arg" | grep -q '[[:space:]]'; then
              file_directive "$msg"
            else
              ntfy_publish "🔄 Syncing…" "Pushing \`$arg\` to GitHub." "arrows_counterclockwise" "low" "" "lemely-acc-sync"
              do_sync "$arg"
            fi ;;
          DIGEST) : > "$DIGESTFILE" ;;   # force a digest on the next beat
          NEXT)
            ntfy_publish "🎯 Next issue" "$(progress_block)
\`\`\`
$(cd "$REPO" && timeout 45 "$PY" scripts/accuracy_board.py next 2>&1 | strip_ansi | head -n 15)
\`\`\`" "dart" "default" "[$(view_action 'Board' 'https://github.com/orgs/LemelyIG/projects/1')]" ;;
          ISSUE\ *)
            # Only "ISSUE <n>" (keyword + exactly one argument) is the
            # command — extra words mean free text ("issue with the fixture
            # renderer") that must fall through to the inbox, not be
            # mis-parsed for a leading digit.
            arg="$(printf '%s' "$msg" | cut -d' ' -f2-)"
            if printf '%s' "$arg" | grep -q '[[:space:]]'; then
              file_directive "$msg"
            else
              n="$(printf '%s' "$arg" | tr -dc '0-9')"
              if [ -n "$n" ]; then
                inbox_append "Prioritise issue #$n: make it your next work item if its dependencies allow. If it is blocked, do not force it — explain why in the note when you check this item off."
                ntfy_publish "📥 Priority filed — issue #$n" "$(progress_block)
The agent picks it up at its next checkpoint (or explains why it cannot)." "inbox_tray" "default" \
                  "[$(view_action 'Issue' "$REPO_URL/issues/$n")]" "" "" "$REPO_URL/issues/$n"
              else
                ntfy_publish "❓ ISSUE needs a number" "Send \`ISSUE 56\` (for example) to prioritise an issue." "question" "low"
              fi
            fi ;;
          BUDGET)
            ntfy_publish "💰 Budget" "$(progress_block)
$(python3 -c "
import sys
try: s = float(sys.argv[1])
except Exception: s = 0.0
c = float(sys.argv[2])
print(f'Ledger spend: \${s:.2f} of \${c:.2f} ({s/c*100:.1f}%) · headroom \${c-s:.2f}')
print('Marks: 50% = \$12.50 · 80% = \$20.00 (one notification each).')
print('Caveat: pre-M0.2 the ledger understates real spend 2-4x and omits thinking tokens — treat as a lower bound. The ceiling is a pre-flight check, not a hard stop.')" \
              "$(state_field spend_usd | tr -dc '0-9.')" "$COST_CEILING_USD" 2>/dev/null)" \
              "moneybag" "default" "[$(ctrl_action Status STATUS)]" ;;
          GATES)
            ntfy_publish "🧪 Gate suite running" "$(progress_block)
scripts/check.sh in the worktree — result follows (up to $((GATES_TIMEOUT / 60))m)." "test_tube" "low"
            run_gates & ;;
          *) file_directive "$msg" ;;
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
    date +%s > "$DIGESTFILE"
    while :; do
      sleep "$HEARTBEAT_SECS"
      run_no="$(cat "$RUNFILE" 2>/dev/null || echo '?')"
      started="$(cat "$STARTFILE" 2>/dev/null || date +%s)"
      elapsed=$(( ( $(date +%s) - started ) / 60 ))
      sha="$(git rev-parse --short HEAD 2>/dev/null)"

      ntfy_publish "Accuracy — working" "$(progress_block)
Run **$run_no** · ${elapsed}m · model \`$MODEL\`

**Latest**
$(recent_commits 2)" "hourglass_flowing_sand" "low" \
        "[$(view_action 'Latest commit' "$(commit_url)"),$(ctrl_action Sync SYNC),$(ctrl_action Pause PAUSE)]" \
        "lemely-acc-heartbeat" "" "$(commit_url)"

      # S3: watch GitHub Actions every beat, not just once the run loop
      # notices — a run can sit inside a single 'claude -p' call for a long
      # time, and CI can turn red on a PR while that's happening.
      check_ci_status

      # stall detection: no new commit across several beats
      if [ "$sha" = "$last_sha" ]; then
        quiet_beats=$((quiet_beats + 1))
        if [ "$quiet_beats" -eq "$STALL_BEATS" ]; then
          ntfy_publish "🐌 Possibly stalled" "$(progress_block)
No new commit for $(( STALL_BEATS * HEARTBEAT_SECS / 60 )) minutes. It may be on a long measurement sweep, or stuck." \
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
          echo "# Accuracy daily digest — $(date '+%Y-%m-%d %H:%M')"; echo
          progress_block; echo
          echo "## Commits (24h)"; git log --since='24 hours ago' --pretty='- `%h` %s' 2>/dev/null | head -60; echo
          echo "## Files changed (24h)"; git diff --stat "@{24 hours ago}" 2>/dev/null | tail -25; echo
          echo "## Open blockers"; sed -n '1,60p' BUILD/BLOCKERS.md 2>/dev/null || echo "none"; echo
          echo "## Inbox tail"; tail -n 20 "$INBOX" 2>/dev/null
        } > /tmp/lemely-acc-digest.md
        ntfy_publish "📊 Accuracy daily digest" "$(progress_block)
$(git log --since='24 hours ago' --oneline 2>/dev/null | wc -l) commits in the last 24h. Full digest attached." \
          "bar_chart" "default" "[$(view_action 'Open repo' "$REPO_URL")]"
        ntfy_attach /tmp/lemely-acc-digest.md "Accuracy digest $(date '+%d %b')" "bar_chart" "default"
      fi

      ntfy_publish "💀 Accuracy supervisor stopped responding" \
        "No heartbeat for ${WATCHDOG_MINUTES}m — the machine or the supervisor died." \
        "skull" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]" "lemely-acc-watchdog" "${WATCHDOG_MINUTES}m"
    done
  ) &
  MONITOR_PID=$!
}

cleanup() {
  [ -n "${MONITOR_PID:-}" ] && kill "$MONITOR_PID" 2>/dev/null
  [ -n "${CONTROL_PID:-}" ] && kill "$CONTROL_PID" 2>/dev/null
  ntfy_cancel "lemely-acc-watchdog"
}
trap cleanup EXIT INT TERM

# --------------------- out-of-session gate sweep ---------------------------
# The full gate suite — scripts/check.sh: pytest, ruff, mypy, lint-imports and
# the web job — takes longer than any wait an agent session can survive. Until
# 2026-08-19 the orchestrator ran it itself, inside 'claude -p', and it never
# once finished: the run hit the background-wait ceiling, the session died and
# took the suite with it, and the next run started the same suite from zero.
# Five consecutive runs did nothing else. /tmp/pytest-of-sico kept one partial
# tmpdir tree per run as the receipt.
#
# The suite is not the agent's job. It costs no tokens and needs no judgement,
# so it runs HERE, in bash, between runs, where nothing terminates it at a
# ceiling. The verdict is handed to the next run as a fact, and the prompt
# forbids the agent from re-running it.
#
# Re-run policy: only when the tree moved since the last sweep. A run that
# commits gets a fresh verdict; a run that commits nothing reuses the verdict
# it already has rather than spending another hour on an unchanged tree.
# check.sh tests the WORKING TREE, not HEAD, so the dirty-file count is part of
# the identity of what was tested and is reported alongside the sha.
gate_sweep() {
  local head dirty glog rc secs started verdict tail_n

  head="$(cd "$REPO" && git rev-parse HEAD 2>/dev/null || echo unknown)"
  dirty="$(cd "$REPO" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"

  if [ -f "$GATEREPORT" ] \
     && [ "$head" = "$(cat "$GATE_SHA" 2>/dev/null)" ] \
     && [ "$dirty" = "$(cat "$GATE_DIRTY" 2>/dev/null)" ]; then
    return 0                     # tree unmoved — the standing verdict still applies
  fi

  glog="$LOGDIR/gates-$(date +%Y%m%d-%H%M%S).log"
  ntfy_publish "🧪 Gate sweep running" "$(progress_block)
scripts/check.sh over \`${head:0:8}\` ($dirty uncommitted). Up to $((GATE_SUITE_TIMEOUT / 60))m; the next run waits for it." \
    "test_tube" "low"

  started=$(date +%s)
  ( cd "$REPO" && timeout "$GATE_SUITE_TIMEOUT" bash scripts/check.sh ) </dev/null >"$glog" 2>&1
  rc=$?
  secs=$(( $(date +%s) - started ))

  case "$rc" in
    0)   verdict="PASS" ;;
    124) verdict="TIMED OUT after $((secs / 60))m — treat as UNKNOWN, not as a failure" ;;
    *)   verdict="FAIL (rc=$rc)" ;;
  esac

  # 60 lines: check.sh prints one PASS/FAIL line per tool plus up to 60 lines of
  # each failure, so a short tail can show the summary while hiding the reason.
  tail_n=60

  cat > "$GATEREPORT" <<EOF
## Gate sweep — already run for you, by the supervisor

\`scripts/check.sh\` ran **outside your session** at $(date -Is), over HEAD
\`$head\` with **$dirty uncommitted file(s)** in the tree. It took $((secs / 60))m.

**Result: $verdict**

\`\`\`
$(strip_ansi < "$glog" | tail -n "$tail_n")
\`\`\`

These rules follow from it, and they override any habit you have:

- **Do not run the full suite yourself.** Not \`scripts/check.sh\`, not a bare
  \`pytest\`, not in the background, not "just to confirm before the PR". It
  outlasts a session, and every run that tried was terminated mid-wait. The
  supervisor runs it between runs and hands you the verdict above.
- **Targeted tests are still yours**, and always were: the test module for the
  code you touched, plus \`ruff\`/\`mypy\` on the files you changed. Run those in
  the **foreground** — they finish in seconds.
- **§9.3's "pytest green" is satisfied by the verdict above** for the sha named
  above, plus CI on the PR. If that sha is not your branch tip, the verdict does
  not cover your latest commit — say so plainly instead of claiming green, and
  let the next sweep pick it up.
- A **FAIL** here is a real red gate: route it to \`accuracy-gate-triage\` (§8).
  Do not re-run the suite hoping for a different answer.
- A **TIMED OUT** is not a failure and not a pass. Report it as unknown.
EOF

  echo "$head"  > "$GATE_SHA"
  echo "$dirty" > "$GATE_DIRTY"

  ntfy_publish "$([ "$rc" -eq 0 ] && echo '✅ Gate sweep PASS' || echo "❌ Gate sweep $verdict")" \
    "$(progress_block)
\`${head:0:8}\` · $((secs / 60))m
\`\`\`
$(strip_ansi < "$glog" | tail -n 25)
\`\`\`" \
    "$([ "$rc" -eq 0 ] && echo 'white_check_mark' || echo 'x')" \
    "$([ "$rc" -eq 0 ] && echo 'default' || echo 'high')"
}

# --------------------------- session continuity -----------------------------
# Until 2026-08-21 every run started a COLD session. Measured over the 14 runs of
# 2026-08-19: a 42,873-token prefix written from scratch each time, 3.79M
# cache-write tokens against 45.4M cache-read, and not one byte of what a run
# wrote was ever read back — the prompt cache is session-scoped with a ~5-minute
# TTL and runs are 10-40 minutes apart. On top of that the agent re-read a 31KB
# mission file, the state file and the board before it could touch any work.
#
# '--resume' keeps the conversation, so that re-orientation simply does not
# happen and the prompt shrinks to a delta (CONTINUE_PROMPT below). But a
# resumed session is not always right, and never right forever:
#   - after a ceiling kill the session's own context says "waiting on a
#     background task"; restoring that belief restores the bug the TIMEOUTFILE
#     handoff exists to break;
#   - after a crash or a usage-limit stop it may be mid-turn;
#   - every resume grows the transcript, so an unbounded chain eventually pays
#     more for in-session compaction than a cold start would have cost.
# So: resume by default, cold on any anomaly, cold every MAX_RESUME_CHAIN runs.
#
# Failure is self-healing rather than sticky. We mint the id ourselves with
# --session-id instead of scraping it from the log, and check the transcript
# exists before resuming; if --resume still fails, claude exits non-zero, that
# is the crash path, and the crash path forces the next run cold. One bad run,
# not a loop.

new_session_id() { cat /proc/sys/kernel/random/uuid; }

# Where claude keeps the transcript for session $1 in $REPO. The project slug is
# the absolute path with every non-alphanumeric byte replaced by '-'.
session_transcript() {
  printf '%s/.claude/projects/%s/%s.jsonl' \
    "$HOME" "$(printf '%s' "$REPO" | tr -c 'a-zA-Z0-9' '-')" "$1"
}

# Decide whether this run continues the previous session. Sets RESUME_SID
# (empty means cold start) and RESUME_CHAIN_N. Must run BEFORE the prompt is
# chosen — the prompt depends on the answer — and before TIMEOUTFILE is consumed.
decide_session() {
  local sid chain reason
  RESUME_SID=""
  sid="$(cat "$SESSIONFILE" 2>/dev/null || true)"
  chain="$(cat "$RESUME_CHAINFILE" 2>/dev/null || echo 0)"
  case "$chain" in ''|*[!0-9]*) chain=0 ;; esac
  RESUME_CHAIN_N="$chain"

  if   [ -z "$sid" ];                        then reason="no previous session recorded"
  elif [ -f "$TIMEOUTFILE" ];                then reason="previous run was killed at the background-task ceiling"
  elif [ "$LAST_RC" != "0" ];                then reason="previous run exited rc=$LAST_RC"
  elif [ "$LAST_LIMITED" = "1" ];            then reason="previous run stopped on a usage limit"
  elif [ "$chain" -ge "$MAX_RESUME_CHAIN" ]; then reason="resume chain hit $MAX_RESUME_CHAIN — shedding accumulated context"
  elif [ ! -f "$(session_transcript "$sid")" ]; then reason="session $sid has no transcript on disk"
  else RESUME_SID="$sid"; reason=""
  fi

  if [ -n "$RESUME_SID" ]; then
    echo "--- run $run: RESUMING session $RESUME_SID (resume $((chain + 1)) of $MAX_RESUME_CHAIN)"
  else
    echo "--- run $run: COLD session — $reason"
  fi
}

# --------------------------- run loop --------------------------------------

# Carried by every prompt, with or without a gate report attached, so the rule
# holds on the very first run too. ACCURACY-MISSION.md §9.3 says "pytest green"
# and says nothing about who runs it; read alone it invites the agent to run the
# whole suite in-session, which is what wedged 2026-08-19. This is the missing
# half of that sentence.
SUITE_RULE="The FULL gate suite (a bare whole-repo pytest, or 'scripts/check.sh' with no --fast) is the SUPERVISOR's job, not yours. It runs between runs, outside your session, and its verdict is handed to you at the top of this prompt when there is one. Measured 2026-08-21: the full backend suite takes 20.2 minutes. Never launch it yourself, foreground or background — it outlasts a session, and every run that tried was terminated mid-wait with nothing landed.

Your in-run check is 'scripts/check.sh --fast [paths]': the same gate list with pytest under xdist and coverage off, narrowable to the tests you touched. Measured 96s on one module. Use it, and read ACCURACY-MISSION.md §9.1 for exactly which gate runs where.

A green --fast run is never sufficient to merge. Where the mission asks for 'pytest green' (§9.3), the proof is the supervisor's verdict above plus CI on the PR — and if that verdict does not cover your branch tip, say so rather than claiming green. You do not need to watch CI yourself: accuracy-pr-land already watches it to conclusion.

Never end a turn waiting on a background job. Either record the command AND its log path in in_the_middle_of so the next run can poll it, or do not start it."

FIRST_PROMPT="Read BUILD/ACCURACY-MISSION.md end to end — it is your complete mission. Then read BUILD/ACCURACY-INBOX.md (act on any directives first), BUILD/ACCURACY-STATE.md, and run '.venv/bin/python scripts/accuracy_board.py next'. Begin execution exactly as ACCURACY-MISSION.md instructs.

$SUITE_RULE"
RESUME_PROMPT="You are resuming the unattended accuracy programme. Read BUILD/ACCURACY-INBOX.md FIRST and act on any unhandled directives. Then read BUILD/ACCURACY-MISSION.md and BUILD/ACCURACY-STATE.md, and run '.venv/bin/python scripts/accuracy_board.py next'. Clean up any dirty working tree with a signed wip commit, then continue from what the inbox, state file and board tell you, following ACCURACY-MISSION.md protocols exactly.

$SUITE_RULE"

# Used only when this run CONTINUES the previous session (see decide_session).
# The point of resuming is that re-orientation is already done, so this prompt
# must not ask for it again — it names only what changed while the session was
# stopped. If you find yourself adding "read the mission" back into this string,
# the resume is buying nothing and MAX_RESUME_CHAIN should be 0 instead.
CONTINUE_PROMPT="Continue the unattended accuracy programme. This is a new run inside the SAME session: you still hold ACCURACY-MISSION.md, its protocols, and everything you established last run. Do not re-read the mission and do not re-derive what you already know.

What you do not hold is anything that changed while you were stopped, so re-read exactly these: BUILD/ACCURACY-INBOX.md (act on any unhandled directive before anything else), BUILD/ACCURACY-STATE.md, and '.venv/bin/python scripts/accuracy_board.py next'. Also re-check the working tree — if it is dirty, commit it with a signed wip commit before continuing.

Treat your own memory of the repo's contents as stale where it matters: commits may have landed, CI may have finished, and a human may have edited files under you. Verify before you rely on it. Then carry on from where you were, following ACCURACY-MISSION.md protocols exactly.

$SUITE_RULE"

ntfy_publish "🚀 Accuracy supervisor started" "$(progress_block)
Host \`$(hostname)\` · model \`$MODEL\` · worktree \`$REPO\`

**Latest**
$(recent_commits 2)" "rocket" "default" \
  "[$(view_action 'Open board' 'https://github.com/orgs/LemelyIG/projects/1'),$(ctrl_action Status STATUS)]"

[ -f "$BLOCKMARK" ] || touch "$BLOCKMARK"
start_monitor
start_control_listener

run=0
LAST_RC=0                 # previous run's exit code, and whether it stopped on a
LAST_LIMITED=0            # usage limit. Both feed decide_session; 'set -u' means
                          # they must exist before the first call, and the seeded
                          # values are the ones that permit a resume — harmless,
                          # because run 1 has no session to resume anyway.
RESUME_SID=""
RESUME_CHAIN_N=0
while [ "$run" -lt "$MAX_RUNS" ]; do
  run=$((run + 1)); echo "$run" > "$RUNFILE"

  # Board-derived completion: all non-H M0/M1/M2 leaves Done. M3/M4 are
  # unscoped by design — this is the mission's stop-and-ask point, so stop.
  if board_complete; then
    ntfy_publish "🎉 M0–M2 COMPLETE" "$(progress_block)
Every non-H sub-issue of epics #24, #35 and #43 is Done after **$run** run(s). M3 (parse-path parity, #53) and M4 (judgment and vision, #54) have no sub-issues yet and need human scoping before anything continues." \
      "tada,white_check_mark" "urgent" \
      "[$(view_action 'Board' 'https://github.com/orgs/LemelyIG/projects/1'),$(view_action 'Pull requests' "$REPO_URL/pulls")]" \
      "" "" "https://github.com/orgs/LemelyIG/projects/1"
    exit 0
  fi

  # ACCURACY-STATE.md defines no 'status' field today; honoured if one is
  # ever added to its contract.
  case "$(state_field status)" in
    COMPLETE)
      ntfy_publish "🎉 Programme marked COMPLETE" "$(progress_block)" "tada" "urgent" \
        "[$(view_action 'Board' 'https://github.com/orgs/LemelyIG/projects/1')]"
      exit 0 ;;
    HALTED)
      ntfy_publish "🛑 Programme HALTED" "$(progress_block)
Orchestrator halted the programme. Blockers attached." "octagonal_sign" "urgent" \
        "[$(view_action 'Open blockers' "$REPO_URL/blob/develop/BUILD/BLOCKERS.md"),$(ctrl_action Resume RESUME)]"
      ntfy_attach "$REPO/BUILD/BLOCKERS.md" "BLOCKERS.md" "warning" "high"
      exit 1 ;;
  esac

  # Re-check the origin/develop-contains-origin/main precondition each run: a
  # human merging develop→main mid-programme legitimately moves main ahead
  # again, and the next feature branch must not be cut until develop is
  # fast-forwarded AND pushed — checked against the pushed refs, matching the
  # startup guard and the mission (accuracy-issue-execute cuts from origin/develop).
  git fetch --quiet origin
  BEHIND="$(git rev-list --count origin/develop..origin/main 2>/dev/null || echo 0)"
  if [ "$BEHIND" != "0" ]; then
    ntfy_publish "🛑 develop fell behind main — holding" "$(progress_block)
origin/develop is $BEHIND commit(s) behind origin/main. Fast-forward and push it:

  git -C /home/sico/Lemely push origin main:develop

(see CONTROLS-ACCURACY.md launch checklist), then send RESUME." \
      "octagonal_sign" "high" "[$(ctrl_action Resume RESUME),$(view_action 'Compare' "$REPO_URL/compare/develop...main")]"
    touch "$PAUSEFILE"
  fi

  if [ -f "$PAUSEFILE" ]; then
    ntfy_publish "⏸ Paused" "$(progress_block)
Holding before run $run. Send RESUME, or delete BUILD/PAUSE in the worktree." "pause_button" "default" \
      "[$(ctrl_action Resume RESUME),$(ctrl_action Status STATUS)]"
    do_sync                      # push everything before you take a look
    while [ -f "$PAUSEFILE" ]; do sleep 20; done
    ntfy_publish "▶️ Resumed" "$(progress_block)" "arrow_forward" "low"
  fi

  # Continue the previous session, or start a cold one? Decided here because the
  # prompt depends on the answer, and while TIMEOUTFILE is still on disk — the
  # block below consumes it.
  decide_session

  # First run ever: ACCURACY-STATE.md still carries the seeded 'run_pointer: none'.
  rp="$(state_field run_pointer)"
  if [ -n "$RESUME_SID" ]; then
    PROMPT="$CONTINUE_PROMPT"
  elif [ "$run" -eq 1 ] && { [ -z "$rp" ] || [ "$rp" = "none" ]; }; then
    PROMPT="$FIRST_PROMPT"
  else
    PROMPT="$RESUME_PROMPT"
  fi

  # Run the full gate suite here, before the agent starts, so the agent never has
  # to wait on it. Blocks for as long as the suite takes — that is the point.
  gate_sweep

  # The standing gate verdict, if there is one. Not consumed: it holds until the
  # tree moves, and every run needs to know both what it says and that running
  # the suite is not this session's job.
  if [ -f "$GATEREPORT" ]; then
    PROMPT="$(cat "$GATEREPORT")

---

$PROMPT"
  fi

  # If the previous run was killed by the background-task wait ceiling, lead with
  # that. It goes FIRST, ahead of the inbox and the state file, because the state
  # file is exactly what will mislead this run: it still says work is "in flight".
  # Consumed once — deleted on read, so a run is told about a timeout only once.
  if [ -f "$TIMEOUTFILE" ]; then
    PROMPT="$(cat "$TIMEOUTFILE")

---

$PROMPT"
    rm -f "$TIMEOUTFILE"
  fi

  # Resume into the recorded session, or mint a new id and record it. The id is
  # ours either way, so the next run never has to scrape one out of the log.
  if [ -n "$RESUME_SID" ]; then
    SESSION_ARGS=(--resume "$RESUME_SID")
    SESSION_DESC="resumed $RESUME_SID"
    echo "$((RESUME_CHAIN_N + 1))" > "$RESUME_CHAINFILE"
  else
    SESSION_ID="$(new_session_id)"
    SESSION_ARGS=(--session-id "$SESSION_ID")
    SESSION_DESC="new $SESSION_ID"
    echo "$SESSION_ID" > "$SESSIONFILE"
    echo 0 > "$RESUME_CHAINFILE"
  fi

  LOG="$LOGDIR/acc-run-$(printf '%04d' "$run")-$(date +%Y%m%d-%H%M%S).log"
  date +%s > "$STARTFILE"
  RUNSTART_SHA="$(git rev-parse HEAD 2>/dev/null)"
  echo "=== accuracy run $run starting $(date -Is) model=$MODEL session=$SESSION_DESC ===" | tee -a "$LOG"

  # </dev/null is not cosmetic. Without it the CLI waits on stdin, prints
  # "no stdin data received in 3s, proceeding without it", and only then starts —
  # and under tmux stdin is a live terminal, so it is also the one input a stray
  # keystroke could reach. The prompt arrives as an argument; stdin is never wanted.
  claude -p "$PROMPT" --model "$MODEL" "${SESSION_ARGS[@]}" \
    --dangerously-skip-permissions --verbose </dev/null >>"$LOG" 2>&1 &
  CLAUDE_PID=$!; echo "$CLAUDE_PID" > "$CLAUDE_PIDFILE"
  wait "$CLAUDE_PID"; rc=$?; rm -f "$CLAUDE_PIDFILE"
  LAST_RC="$rc"; LAST_LIMITED=0     # LAST_LIMITED is raised by the outcome block

  echo "=== accuracy run $run exited rc=$rc $(date -Is) ===" >>"$LOG"
  mins=$(( ( $(date +%s) - $(cat "$STARTFILE") ) / 60 ))
  DIFFSUM="$(run_diff_summary "$RUNSTART_SHA")"

  # --- programme-specific notices ---------------------------------------
  rm -f "$BOARD_CACHE"           # the run just changed the world; refetch
  check_new_prs
  check_ci_status
  check_h_blocking
  check_spend
  check_not_reportable "$LOG"
  check_milestone_transition

  # --- new blockers ------------------------------------------------------
  if [ -f BUILD/BLOCKERS.md ] && [ BUILD/BLOCKERS.md -nt "$BLOCKMARK" ]; then
    ntfy_publish "⚠️ New blocker recorded" "$(progress_block)
The agent hit something it couldn't resolve and moved on. Details attached." "warning" "high" \
      "[$(view_action 'Open blockers' "$REPO_URL/blob/develop/BUILD/BLOCKERS.md"),$(ctrl_action 'Send guidance' 'STATUS')]"
    ntfy_attach BUILD/BLOCKERS.md "BLOCKERS.md" "warning" "high"
    touch "$BLOCKMARK"
  fi

  # --- outcome -----------------------------------------------------------
  if tail -n 80 "$LOG" | grep -qiE "session limit|usage limit|rate limit|limit reached|overloaded|429"; then
    LAST_LIMITED=1              # a run cut off at a limit may be mid-turn; the next
                                # one starts cold rather than resuming into that
    wait_secs="$(parse_reset_seconds "$LOG")"
    if [ -n "$wait_secs" ]; then wait_secs=$((wait_secs + LIMIT_RESUME_MARGIN)); precision="from the limit message"
    else wait_secs="$BACKOFF_LIMIT_FALLBACK"; precision="estimated — no reset time given"; fi

    if [ "$wait_secs" -gt "$MAX_LIMIT_WAIT" ]; then
      ntfy_publish "🛑 Long limit window — stopping" "$(progress_block)
Reset is ~$((wait_secs / 3600))h away (likely the weekly cap). Stopping cleanly; nothing is lost.
Relaunch after the reset:
\`tmux new -s lemely-acc -c $REPO /home/sico/Lemely/supervisor-accuracy.sh\`

$DIFFSUM" "octagonal_sign" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]"
      exit 0
    fi

    if should_notify_failure "$LOG"; then
      ntfy_publish "⏳ Usage limit — waiting" "$(progress_block)
Resuming in **$((wait_secs / 60))m** (~$(date -d "+$wait_secs seconds" '+%H:%M')), $precision.
Ran ${mins}m before hitting the wall.

$DIFFSUM" "hourglass_flowing_sand" "low" "[$(ctrl_action Status STATUS)]" "lemely-acc-limit"
    fi
    sleep "$wait_secs"
    ntfy_publish "▶️ Limit reset — resuming" "$(progress_block)" "arrow_forward" "low" "" "lemely-acc-limit"

  elif [ "$rc" -ne 0 ]; then
    if should_notify_failure "$LOG"; then
      ntfy_publish "⚠️ Run $run crashed (rc=$rc)" "$(progress_block)
Ran ${mins}m · retrying in $((BACKOFF_CRASH / 60))m · log attached.

$DIFFSUM" "warning" "high" \
        "[$(ctrl_action 'Skip task' SKIP),$(ctrl_action Pause PAUSE),$(view_action 'Open repo' "$REPO_URL")]"
      ntfy_attach "$LOG" "Crash log — accuracy run $run (rc=$rc)" "page_facing_up" "high"
    fi
    sleep "$BACKOFF_CRASH"

  # A run killed by the background-task wait ceiling exits rc=0 and is
  # indistinguishable from a clean finish by return code alone — the only
  # evidence is the line the CLI prints on its way out. Detect it, and hand the
  # fact forward: without this the next run reads a state file that says work is
  # "in flight", waits on it again, and dies the same way (runs 1-8, 2026-08-19).
  # Scan the WHOLE log, not the tail: the CLI prints this line early (line 2 in
  # every observed case) and then keeps streaming, so a tail window would miss it
  # on any long run — silently restoring the bug. Anchored on the CLI's exact
  # "<N>s; terminating" phrasing so prose that merely discusses timeouts is not
  # mistaken for one.
  elif grep -qiE "Background tasks still running after [0-9]+s; terminating" "$LOG"; then
    stuck_on="$(state_field in_the_middle_of)"
    cat > "$TIMEOUTFILE" <<EOF
## ⚠ The previous run (run $run) was TERMINATED, not finished.

It ran ${mins}m and was killed by the background-task wait ceiling
($((CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS / 60000)) minutes) while waiting on
background work. It exited rc=0, so nothing else marks this as a failure — this
notice is the only record. Its final summary in the log is NOT a completion
report; it is a snapshot of a run that was cut off mid-wait.

What it said it was in the middle of: ${stuck_on:-(nothing recorded)}

Act on this before anything else:

1. **Whatever it was waiting on is gone.** Background tasks and workflows do not
   survive the session that launched them (ACCURACY-MISSION.md §7). Any \`wf_…\`
   id in ACCURACY-STATE.md is a dead handle, not something you can collect. Do
   not wait on it. Do not poll it. Re-run it from scratch if its result is still
   needed.
2. **Do not simply re-arm the same wait** — that is the exact loop this notice
   exists to break. If you are about to background a long task and wait on it,
   run it in the foreground instead, or narrow it (§9: run the smallest thing
   that answers the question; the full suite runs once, before PR).
3. **Correct \`in_the_middle_of\`** to a fact the next run can act on without a
   live handle — e.g. "#56: implemented, unreviewed" — via
   \`scripts/accuracy_board.py state set in_the_middle_of "…"\`.
4. If this has now happened on consecutive runs for the same item, stop
   retrying it and record a blocker in BUILD/BLOCKERS.md (§11).
EOF
    ntfy_publish "⏱ Run $run hit the background-task ceiling" "$(progress_block)
Ran ${mins}m, then was terminated waiting on background work (rc=0, so it is not counted as a crash).
Waiting on: ${stuck_on:-(nothing recorded)}
The next run is being told explicitly, so it does not re-arm the same wait.

$DIFFSUM" "hourglass,warning" "high" \
      "[$(ctrl_action Pause PAUSE),$(view_action 'Latest commit' "$(commit_url)")]" \
      "lemely-acc-bgceiling"
    ntfy_attach "$LOG" "Timeout log — accuracy run $run" "page_facing_up" "default"
    sleep 20

  else
    rm -f "$TIMEOUTFILE"        # a genuinely clean run clears any stale handoff
    # Say which it will actually be. "Fresh context" was unconditional and is now
    # the exception, and a notice that misreports this hides a stuck resume chain.
    if [ "$((RESUME_CHAIN_N + 1))" -ge "$MAX_RESUME_CHAIN" ]; then
      next_desc="restarting with fresh context (resume chain full)"
    else
      next_desc="continuing the same session (resume $((RESUME_CHAIN_N + 1))/$MAX_RESUME_CHAIN)"
    fi
    ntfy_publish "🔄 Run $run checkpointed" "$(progress_block)
${mins}m · $next_desc.

$DIFFSUM" "recycle" "min" "[$(view_action 'Latest commit' "$(commit_url)")]" "lemely-acc-checkpoint" "" "$(commit_url)"
    sleep 20
  fi
done

ntfy_publish "🛑 MAX_RUNS=$MAX_RUNS reached" "$(progress_block)
Safety valve tripped." "octagonal_sign" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]"
exit 1
