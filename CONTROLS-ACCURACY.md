# Steering the accuracy programme

Publish a message to the control topic `lemely-acc-ctl-bqlsqcY9FfbfQd` from the
ntfy app on your phone, tap an action button on any notification, or run
`./nudge-accuracy <thing>` on the laptop. The outbound topic (subscribe to this
one) is `lemely-acc-EF5H6SKKGxyJseM`; both live on `http://home-server:7532`.

This is the accuracy programme's channel. The redesign build has its own
supervisor (`supervisor.sh`), topics and `CONTROLS.md` — the two must never run
at the same time, and `supervisor-accuracy.sh` refuses to start while
`supervisor.sh` is up.

## Launching

```bash
tmux new -s lemely-acc -c /home/sico/Lemely-worktrees/accuracy \
  /home/sico/Lemely-worktrees/orch/supervisor-accuracy.sh
```

Two different checkouts, and the `-c` is what keeps them apart:

| | path | why |
|---|---|---|
| the script | `/home/sico/Lemely-worktrees/orch` | pinned to `chore/accuracy-orchestration-and-decisions`; nothing else churns it |
| its cwd | `/home/sico/Lemely-worktrees/accuracy` | the tree it drives; its branch changes every issue |

Never run it from the accuracy worktree, and never from `/home/sico/Lemely`. On
2026-08-19 the supervisor was launched from the accuracy worktree, so the live
script was whatever the checked-out feature branch happened to carry: a fix
committed to the orchestration branch sat unused for five runs. Operator
infrastructure must not be versioned by the branch it operates on.

If `/home/sico/Lemely-worktrees/orch` is missing, recreate it — it is a
disposable view of a tracked branch, not a place to keep uncommitted work:

```bash
git -C /home/sico/Lemely worktree add /home/sico/Lemely-worktrees/orch \
  chore/accuracy-orchestration-and-decisions
```

The script refuses to start until every launch-checklist item below holds.

## LAUNCH CHECKLIST

Work through this once, **in order** — the order matters: everything that
touches `develop` (steps 3–4) must happen *before* the worktree is created
(step 5), because `git worktree add ... develop` checks out whatever local
`develop` currently points to, and `git fetch . main:develop` (step 4) fails
outright once `develop` is checked out in another worktree. The old ordering
here created the worktree first and only then tried to fast-forward `develop`
— guaranteed to fail on the last command of step 4. Steps 4, 5, 6 and 7 are
also enforced by startup guards, so a miss is loud, not silent.

1. **ntfy server reachable at `home-server:7532`.** Check with:

   ```bash
   curl -s -m 5 http://home-server:7532/v1/health && echo OK || echo "ntfy DOWN"
   ```

   See "Known environment state" below for what was true on this machine when
   this file was last verified, and the command to start the server if it's
   down. The supervisor still works with ntfy down — every notify path fails
   silently — but you get no heartbeats, no controls, and the phone is blind.
   Fix the server before an unattended stretch.

2. **`GEMINI_API_KEY` exported** in the shell that launches tmux (never in
   `lemely.toml`, never committed). `lemely doctor` (step 5) confirms it.

3. **The accuracy-programme setup is committed and pushed to `develop`.**
   `BUILD/ACCURACY-MISSION.md`, `BUILD/ACCURACY-STATE.md`,
   `BUILD/ACCURACY-INBOX.md`, `scripts/accuracy_board.py`,
   `scripts/accuracy_notify.sh`, all six `.claude/workflows/accuracy-*.js`
   (including `accuracy-pr-land.js`) and all five `.claude/agents/accuracy-*.md`
   started life untracked in `/home/sico/Lemely`. Until every one of them is
   committed and pushed to `develop`, a fresh worktree — checked out FROM
   `develop` — simply does not contain them, and the supervisor refuses to
   start (see step 6).

4. **`develop` fast-forwarded to `main`, and PUSHED — before you create the
   worktree.** Feature branches are cut from `origin/develop`, so it's the
   PUSHED pair that governs everywhere (the mission, the supervisor's startup
   guard and its per-run recheck all compare `origin/develop..origin/main`,
   never a local-only ref). This fast-forward is yours to perform, never the
   agent's, and it must happen here, before step 5:

   ```bash
   git -C /home/sico/Lemely fetch origin
   git -C /home/sico/Lemely push origin main:develop
   git -C /home/sico/Lemely fetch . main:develop
   # the last command fails if develop is checked out in some tree — it must
   # run BEFORE step 5 creates the accuracy worktree on develop; if you did
   # step 5 first, run 'git merge --ff-only main' inside that worktree instead
   ```

5. **The accuracy worktree exists, with its own venv.** Worktrees must live
   outside the repo (nothing in-repo is broadly gitignored and the supervisor's
   agent auto-commits dirty trees), and the worktree needs its own venv because
   the main `.venv` editable-installs `lemely` from `/home/sico/Lemely`. Do
   this only after steps 3–4, so the checked-out `develop` already has the
   setup and is caught up with `main`:

   ```bash
   git -C /home/sico/Lemely worktree add /home/sico/Lemely-worktrees/accuracy develop
   cd /home/sico/Lemely-worktrees/accuracy
   python -m venv .venv
   .venv/bin/pip install -e ".[dev,ui,web,db]"
   .venv/bin/lemely doctor
   ```

6. **The mission files are in the worktree — verify, don't assume.** If step
   3 was skipped or missed a file, this is where it shows up:

   ```bash
   for f in BUILD/ACCURACY-MISSION.md BUILD/ACCURACY-STATE.md BUILD/ACCURACY-INBOX.md \
            scripts/accuracy_board.py scripts/accuracy_notify.sh \
            .claude/workflows/accuracy-issue-execute.js .claude/workflows/accuracy-review.js \
            .claude/workflows/accuracy-measure.js .claude/workflows/accuracy-label-batch.js \
            .claude/workflows/accuracy-gate-triage.js .claude/workflows/accuracy-pr-land.js \
            .claude/agents/accuracy-implementer.md .claude/agents/accuracy-reviewer.md \
            .claude/agents/accuracy-measurer.md .claude/agents/accuracy-labeller.md \
            .claude/agents/accuracy-scribe.md; do
     [ -f "/home/sico/Lemely-worktrees/accuracy/$f" ] || echo "MISSING: $f"
   done
   ```

   The supervisor's own startup guard runs this same check and names every
   miss, so this is a preview, not the only line of defence.

7. **The redesign supervisor is not running.** Two unattended agents race on
   commits and pushes. Check and, if needed, stop it:

   ```bash
   pgrep -af 'supervisor\.sh'
   ```

## Known environment state (verified 2026-08-18)

- **ntfy.** No systemd unit manages the ntfy *server* on this machine (only a
  client unit exists, under `/home/sico/ntfy_2.27.0_linux_amd64/client/`,
  which is unrelated). At the time this was checked, a bare `ntfy serve`
  process happened to be running and answering; that is not guaranteed to
  survive a reboot or an accidental `kill`, since nothing supervises it. Start
  it yourself if the health check above says DOWN:

  ```bash
  sudo ntfy serve --config /etc/ntfy/server.yml &
  curl -s -m 5 http://home-server:7532/v1/health && echo OK || echo "ntfy DOWN"
  ```

- **shellcheck is NOT installed** on this machine. `bash -n` (syntax only) is
  the verification available for `supervisor-accuracy.sh`, `nudge-accuracy`
  and `scripts/accuracy_notify.sh` — it will not catch shellcheck-class issues
  (unquoted expansions, SC2086-style pitfalls, etc.). Install shellcheck
  before trusting anything beyond "the script parses."

- **4 CPU cores** (`nproc` → 4). Any workflow's internal fan-out (e.g.
  `accuracy-review`'s per-dimension reviewers, or `accuracy-label-batch`'s QA
  passes) should run at most 2 agents concurrently on this box — more than
  that just contends for the same 4 cores and slows everything down, it
  doesn't parallelise real work.

- **`lemely/runtime/notify.py` hardcodes port 80.** `_NTFY_BASE =
  "http://home-server"` with no port, i.e. `:80` — not this supervisor's
  `:7532`. `supervisor-accuracy.sh` exports `LEMELY_NTFY_TOPIC` so
  `budget_notify()` and friends are at least addressed (not a silent no-op
  for lack of a topic), but a Python-side call still targets the wrong port
  on this deployment. `notify.py` is production code with tests and is out of
  scope for this programme to change. **Direct any agent-initiated
  notification through `scripts/accuracy_notify.sh` instead** — it's bash, it
  hardcodes `:7532`, and it's the reliable path.

## Workflows

The programme's repeated work runs as `Workflow({name: '<meta.name>', args: {...}})`
calls, not ad hoc prompts. Six live in `.claude/workflows/`:

| Workflow | Owns |
|---|---|
| `accuracy-issue-execute` | One issue end to end: scope, TDD implement, gates, adversarial review, opus verdict. Does **not** open the PR. |
| `accuracy-review` | Adversarial multi-dimension review of a diff before a PR opens. |
| `accuracy-measure` | One honest measurement sweep: costed preflight, cache-aware sweep, opus adjudication against the A/A floor. "Not reportable" is a valid outcome. |
| `accuracy-label-batch` | Prepares/QAs one batch of human blind labelling. Never produces labels itself. |
| `accuracy-gate-triage` | Diagnoses a red gate or failing CI job: reproduce, race root-cause hypotheses, opus names the cause and whether to fix the code or the gate. |
| `accuracy-pr-land` | **Owns the whole PR lifecycle** for one issue: push the branch, open the PR (body carries `Closes #<issue>`), board → In review, watch CI to conclusion, route a red run into `accuracy-gate-triage`, merge feature→develop only when CI is green and the review was clean, delete the branch, board → Done, update state. **Hard limit: merges feature→develop only, never touches `main`.** |

Only ONE `accuracy-issue-execute` may run at a time — they all check out
branches in the same worktree, so two in parallel corrupt each other.

## Keywords

| Send | What happens |
|---|---|
| `STATUS` | Milestone progress bars from the GitHub board, what is in flight, open H issues, review rate against the 10% budget, Gemini spend against $25.00, recent commits. |
| `NEXT` | The next unblocked Ready issue, straight from `scripts/accuracy_board.py next`, with its branch name and why it was picked. |
| `ISSUE <n>` | Files a directive to prioritise issue #n next. If #n is blocked by the dependency graph the agent explains why instead of forcing it. |
| `BUDGET` | Ledger spend vs the $25.00 ceiling, headroom, the 50%/80% marks — with the caveat that pre-M0.2 the ledger understates real spend 2-4x. |
| `GATES` | Runs `scripts/check.sh` (the full gate suite) in the worktree and reports PASS/FAIL with the tail of the log. Can take up to 30 minutes. |
| `SYNC` | Pushes every local branch that's ahead of its remote (or has no remote yet) to GitHub, then reports. Never force-pushes, never commits for you. |
| `SYNC <branch>` | Same, limited to one branch. |
| `PAUSE` | Syncs, then holds after the current run finishes. Nothing is lost. |
| `STOP` | Kills the current run immediately, then holds. Work is committed to its last checkpoint. |
| `RESUME` | Continues. |
| `SKIP` | Tells the agent to move its current issue back to Backlog with a reason (via `accuracy_board.py block`) and take the next one. |
| `DIGEST` | Forces the daily digest immediately. |
| *anything else* | Filed in `BUILD/ACCURACY-INBOX.md` as a directive. The agent reads the inbox FIRST on every run and it outranks its own queue. |

## What each notification means, and what to do

| Notification | Priority | What to do |
|---|---|---|
| Supervisor started | default | Nothing. |
| Heartbeat (every 10m, updates in place) | low | Nothing — its absence is the signal. |
| PR opened to `develop` | high | Review it when convenient; tapping opens the PR. `accuracy-pr-land` owns the rest of the lifecycle (CI watch, gate-triage on red, merge on green) and merges its own feature→develop PRs after gates pass and review is clean, so this is a review window, not a gate. |
| CI red on PR #n | high | Usually informational: `accuracy-pr-land` already routes a red run into `accuracy-gate-triage` on its own. Tap "Checks" to look; step in yourself only if it stays red across several beats, or if you want to intervene before the automatic triage does. Fires once per (PR, commit) — a new push gets a fresh chance to notify. |
| H issue now blocks #n | **urgent** | You are the only unblock. Do the human task (#49 split approval, #51 re-label sample, #52 CAIE adjudications) or the programme thread stays parked. The agent will never close or work around an H issue. |
| Spend crossed 50% / 80% of ceiling | high / urgent | Check `BUDGET`, decide whether to raise the ceiling in `lemely.toml` or pause. Both ceilings are pre-flight checks, not hard stops — a single call can overshoot. |
| Result adjudicated NOT REPORTABLE | high | Informational: a measurement fell below the A/A churn floor or an n-floor and was correctly withheld. This is the instrument working. |
| Milestone complete (board) | high | Skim the merged PRs; check `BUILD/DECISIONS.md` for anything recorded (the M0.3 A/A floor lands there). |
| New blocker recorded | high | Read the attached BLOCKERS.md; answer with a free-text directive if you can unblock. |
| Possibly stalled | default | Often a long measurement sweep. `STATUS` first; `SKIP` if genuinely stuck. |
| Run crashed / usage limit | high / low | Nothing — it retries or waits on its own. Repeated identical crashes are deduped to one notice per 30 minutes. |
| develop fell behind main | high | You merged develop→main mid-programme; fast-forward develop again (checklist item 4) and send `RESUME`. |
| M0–M2 COMPLETE | **urgent** | The scoped programme is done. M3/M4 have no sub-issues by design — scoping them is a human decision. |
| Watchdog (machine died) | **urgent** | The supervisor missed its dead-man's switch. Check the machine and tmux session. |
| Daily digest | default | 24h of commits, blockers and progress, attached as a file. |

## Taking the wheel

`PAUSE`, wait for the "Paused" notice (it syncs first), then open a second tmux
window and run `claude` interactively **in the worktree**
(`cd /home/sico/Lemely-worktrees/accuracy`). All state is on disk and on the
GitHub board, so you can talk to it normally, make changes, commit (signed) —
then `RESUME`. Do not work in `/home/sico/Lemely` while the programme runs:
imports and branches would cross between the trees.

## When an H issue blocks the run

H-numbered issues (#49, #51, #52, and any new ones) are human tasks. The agent
must never close one, never mark it done, and must block rather than work
around it — that rule is enforced in `scripts/accuracy_board.py` and restated
in the mission. When you get the urgent "H issue now blocks" notice:

1. Open the H issue (the notification's tap target) and do the task it asks.
2. Close the issue yourself on GitHub when done.
3. Nothing else needed — the agent re-reads the board every run and picks the
   unblocked work up on its own. `RESUME` only if you also paused.

While an H issue blocks one thread, the agent continues on independent issues;
the run only goes quiet when nothing unblocked remains.

## Notes

- All GitHub links point at `develop`, where merged work lands; `main` moves
  only when a human merges the develop→main PR.
- The tracker of record is the GitHub board ("Lemely Progress" #1, epic #23),
  not a checklist file. `BUILD/ACCURACY-STATE.md` holds only the thin resume
  pointer the supervisor greps.
- One-off notifications from your own shell: `scripts/accuracy_notify.sh
  "<title>" "<message>" [tags] [priority]` (always exits 0). Prefer it for
  agent-initiated notifications too — see "Known environment state" above for
  why `lemely/runtime/notify.py`'s port-80 default makes it unreliable on
  this deployment, even with `LEMELY_NTFY_TOPIC` exported.
- Real-paper fixtures under `tests/fixtures/real-papers/` are a minor's actual
  handwritten exam scripts. They never leave the repo: the supervisor's attach
  path hard-refuses them, and nothing may quote or redistribute them.
