#!/usr/bin/env bash
# Lemely unattended ACCURACY-PROGRAMME supervisor.
#
# Sibling of supervisor.sh (the redesign supervisor). Independent script,
# independent ntfy topics, and it runs in the dedicated accuracy worktree at
# /home/sico/Lemely-worktrees/accuracy — never in /home/sico/Lemely itself.
# supervisor.sh is untouched by this file and must never run at the same time.
#
# Run inside tmux:  tmux new -s lemely-acc './supervisor-accuracy.sh'
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

# --------------------------- run loop --------------------------------------

FIRST_PROMPT="Read BUILD/ACCURACY-MISSION.md end to end — it is your complete mission. Then read BUILD/ACCURACY-INBOX.md (act on any directives first), BUILD/ACCURACY-STATE.md, and run '.venv/bin/python scripts/accuracy_board.py next'. Begin execution exactly as ACCURACY-MISSION.md instructs."
RESUME_PROMPT="You are resuming the unattended accuracy programme. Read BUILD/ACCURACY-INBOX.md FIRST and act on any unhandled directives. Then read BUILD/ACCURACY-MISSION.md and BUILD/ACCURACY-STATE.md, and run '.venv/bin/python scripts/accuracy_board.py next'. Clean up any dirty working tree with a signed wip commit, then continue from what the inbox, state file and board tell you, following ACCURACY-MISSION.md protocols exactly."

ntfy_publish "🚀 Accuracy supervisor started" "$(progress_block)
Host \`$(hostname)\` · model \`$MODEL\` · worktree \`$REPO\`

**Latest**
$(recent_commits 2)" "rocket" "default" \
  "[$(view_action 'Open board' 'https://github.com/orgs/LemelyIG/projects/1'),$(ctrl_action Status STATUS)]"

[ -f "$BLOCKMARK" ] || touch "$BLOCKMARK"
start_monitor
start_control_listener

run=0
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

  # First run ever: ACCURACY-STATE.md still carries the seeded 'run_pointer: none'.
  rp="$(state_field run_pointer)"
  if [ "$run" -eq 1 ] && { [ -z "$rp" ] || [ "$rp" = "none" ]; }; then PROMPT="$FIRST_PROMPT"; else PROMPT="$RESUME_PROMPT"; fi

  LOG="$LOGDIR/acc-run-$(printf '%04d' "$run")-$(date +%Y%m%d-%H%M%S).log"
  date +%s > "$STARTFILE"
  RUNSTART_SHA="$(git rev-parse HEAD 2>/dev/null)"
  echo "=== accuracy run $run starting $(date -Is) model=$MODEL ===" | tee -a "$LOG"

  claude -p "$PROMPT" --model "$MODEL" \
    --dangerously-skip-permissions --verbose >>"$LOG" 2>&1 &
  CLAUDE_PID=$!; echo "$CLAUDE_PID" > "$CLAUDE_PIDFILE"
  wait "$CLAUDE_PID"; rc=$?; rm -f "$CLAUDE_PIDFILE"

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
    wait_secs="$(parse_reset_seconds "$LOG")"
    if [ -n "$wait_secs" ]; then wait_secs=$((wait_secs + LIMIT_RESUME_MARGIN)); precision="from the limit message"
    else wait_secs="$BACKOFF_LIMIT_FALLBACK"; precision="estimated — no reset time given"; fi

    if [ "$wait_secs" -gt "$MAX_LIMIT_WAIT" ]; then
      ntfy_publish "🛑 Long limit window — stopping" "$(progress_block)
Reset is ~$((wait_secs / 3600))h away (likely the weekly cap). Stopping cleanly; nothing is lost.
Rerun \`./supervisor-accuracy.sh\` after the reset.

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

  else
    ntfy_publish "🔄 Run $run checkpointed" "$(progress_block)
${mins}m · restarting with fresh context.

$DIFFSUM" "recycle" "min" "[$(view_action 'Latest commit' "$(commit_url)")]" "lemely-acc-checkpoint" "" "$(commit_url)"
    sleep 20
  fi
done

ntfy_publish "🛑 MAX_RUNS=$MAX_RUNS reached" "$(progress_block)
Safety valve tripped." "octagonal_sign" "urgent" "[$(view_action 'Open repo' "$REPO_URL")]"
exit 1
