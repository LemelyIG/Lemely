export const meta = {
  name: 'accuracy-pr-land',
  description: 'Own the PR lifecycle end to end for one accuracy-programme issue: push the branch, open the PR, watch CI to conclusion, route a red run into accuracy-gate-triage, and merge feature -> develop only when CI is green and the review was clean. HARD RULE: base must be develop — this workflow refuses at validation time if asked to touch main; develop -> main is opened and merged by a human, never here.',
  phases: [
    { title: 'Open', detail: 'One sonnet agent verifies the branch is ahead of base, pushes it, opens the PR with gh pr create, and links it on the board via accuracy_board.py review' },
    { title: 'Watch', detail: 'One sonnet agent polls CI (test x3, pre-commit, web) to conclusion with gh pr checks --watch, capped, and reports per-job results — a timeout is reported as a timeout, never a pass' },
    { title: 'Triage', detail: 'CONDITIONAL: only runs if CI came back red. Calls the sibling accuracy-gate-triage workflow inline, guarded by try/catch so a throw degrades to a reported failure instead of killing this run' },
    { title: 'Land', detail: 'One agent with no model override (inherits Opus) decides, from explicit booleans it cannot fudge, whether every merge precondition holds; merges feature -> develop only then, marks the issue Done, and clears in_the_middle_of' },
  ],
}

// -------------------------------------------------------------- ARGS-SHIM-V1
// `args` reaches a workflow script as a JSON *STRING*, not the object the
// caller passed. Measured 2026-08-21 with a zero-agent probe: invoking
// Workflow({name, args: {issue: 56, head: 'HEAD'}}) delivered the literal
// text '{"issue":56,"head":"HEAD"}', for which `typeof args === 'string'` and
// every `args.foo` read is `undefined`. The binding is mutable, so parsing it
// back in place here is enough — no read below this line had to change.
//
// Without this, accuracy-pr-land does not fail; it runs on defaults.
// Its guard would fire and return missing-args, so the failure is loud — but the
// caller reads that as 'the workflow refused' rather than 'the args never arrived'.
// Double-encoding is handled too (a string that parses to another string).
{
  let depth = 0
  while (typeof args === 'string' && depth < 3) {
    const raw = args.trim()
    if (raw === '') { args = {}; break }
    try {
      args = JSON.parse(raw)
    } catch (e) {
      log(`accuracy-pr-land: args arrived as a string that is not JSON (${String((e && e.message) || e)}): ${raw.slice(0, 200)}`)
      return { ok: false, error: 'unparseable-args', detail: raw.slice(0, 500) }
    }
    depth++
  }
  if (args === null || args === undefined) args = {}
  if (typeof args !== 'object' || Array.isArray(args)) {
    const shape = Array.isArray(args) ? 'array' : typeof args
    log(`accuracy-pr-land: args must be an object, got ${shape}. Call as Workflow({ name: 'accuracy-pr-land', args: { ... } }).`)
    return { ok: false, error: 'bad-args-shape', detail: `expected object, got ${shape}` }
  }
}

// ---------------------------------------------------------------- args guard
if (!args || args.issue === undefined || args.issue === null || args.issue === '' || !args.branch) {
  log('accuracy-pr-land: missing required argument(s). Call as workflow("accuracy-pr-land", { issue: <number>, branch: "<feature branch, from accuracy_board.py start>", base: "develop" (optional, default and only allowed value) }).')
  return { ok: false, error: 'missing-args', detail: 'args.issue and args.branch are both required, e.g. { issue: 25, branch: "feature/accuracy-25-eval-record-model" }' }
}
const issue = Number(args.issue)
if (!Number.isInteger(issue) || issue <= 0) {
  log(`accuracy-pr-land: args.issue must be a positive integer GitHub issue number, got: ${JSON.stringify(args.issue)}`)
  return { ok: false, error: 'bad-issue-arg', detail: `unparseable issue number: ${JSON.stringify(args.issue)}` }
}
const branch = String(args.branch)
if (!branch.startsWith('feature/accuracy-')) {
  log(`accuracy-pr-land: branch '${branch}' does not look like a board-issued branch (expected feature/accuracy-<issue>-<slug>, the exact string printed by 'accuracy_board.py start ${issue}'). Refusing to guess; proceeding only because the caller is responsible for passing the real value, but flagging it loudly.`)
}

// HARD RULE (C-PR): this workflow may merge feature -> develop ONLY. It must never merge or
// push to main. develop -> main is opened for a human and merged by a human. Enforced here,
// at validation time, before any agent runs — not left to an agent's judgment.
const base = (args.base !== undefined && args.base !== null && args.base !== '') ? String(args.base) : 'develop'
if (base !== 'develop') {
  log(`accuracy-pr-land: REFUSING. base must be 'develop', got '${base}'. This workflow never merges or pushes to main — develop -> main is opened for a human and merged by a human.`)
  return { ok: false, error: 'base-must-be-develop', detail: `base='${base}' is not allowed here; only 'develop' is automated` }
}

const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'

log(`accuracy-pr-land: landing #${issue} from ${branch} into ${base} at ${ROOT}`)

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} — run every command from this directory (absolute paths only; your cwd resets between bash calls).
Repo: github.com/LemelyIG/Lemely. Python venv at ${ROOT}/.venv — activate with 'source ${ROOT}/.venv/bin/activate'. If it does not exist, bootstrap it: cd ${ROOT} && python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]" — never reuse the main repo's .venv at /home/sico/Lemely, which editable-installs lemely from that other tree and silently imports the wrong code.

ISSUE: #${issue}. BRANCH: ${branch}. BASE: ${base} (this is the only base this workflow will ever touch — never main).
CALLER CONTEXT (may carry a plan, gate results, and an accuracy-review verdict from accuracy-issue-execute; use it if present, re-derive from the issue/commits if absent): ${JSON.stringify(args)}

BOARD: scripts/accuracy_board.py is the ONLY sanctioned interface to GitHub issues and the project board — it carries the H-issue guard. Never call 'gh api graphql' to mutate the board. Subcommands relevant here:
  accuracy_board.py review <issue> --pr <url>          -> sets In review, comments the PR link
  accuracy_board.py done <issue>                        -> sets Done and closes the issue; REFUSES H-numbered issues with exit code 2 — that exit code is a CORRECT outcome to report, not an error
  accuracy_board.py state set <key> <value>

STANDING RULES (non-negotiable):
- Never push to or merge into main. Never force-push. Never delete the base branch.
- Never weaken a gate to get green: no loosened thresholds, no deleted assertions, no skip/xfail, no widened tolerances, no narrowed denominators, and never re-run a red check hoping it flakes green without understanding why it was red.
- H-numbered issues (#34 #48 #49 #50 #51 #52 #55 #60) are human-only: if 'accuracy_board.py done' refuses one (exit 2), that is correct — do not retry it, do not close the issue another way.
- GEMINI_API_KEY lives in the environment only — never print it, never put it in a PR body or comment.
- CI is four jobs (.github/workflows/ci.yml): 'test' on Python 3.12, 3.13 and 3.14 (matrix — three separate checks), 'pre-commit', and 'web'. All must be green.
`

// ---------------------------------------------------------------- schemas
const OPEN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    branch_exists: { type: 'boolean' },
    commits_ahead_of_base: { type: 'integer', description: 'git rev-list --count <base>..<branch>; 0 means nothing to land' },
    pushed: { type: 'boolean' },
    opened: { type: 'boolean', description: 'true only if gh pr create succeeded and a PR number was returned' },
    pr_number: { type: 'integer', description: '0 if not opened' },
    pr_url: { type: 'string', description: 'empty string if not opened' },
    board_updated: { type: 'boolean', description: 'true only if accuracy_board.py review <issue> --pr <url> exited 0' },
    body_file_path: { type: 'string', description: 'absolute path of the PR body file you wrote and passed via --body-file' },
    blockers: { type: 'array', items: { type: 'string' }, description: 'Anything that stopped the open; empty if opened=true' },
  },
  required: ['branch_exists', 'commits_ahead_of_base', 'pushed', 'opened', 'pr_number', 'pr_url', 'board_updated', 'body_file_path', 'blockers'],
}

const WATCH_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    conclusion: { type: 'string', enum: ['success', 'failure', 'timeout'], description: 'timeout is its own outcome — never report a timeout as success or as failure' },
    jobs: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          name: { type: 'string', description: 'e.g. "test (3.12)", "test (3.13)", "test (3.14)", "pre-commit", "web"' },
          conclusion: { type: 'string', enum: ['success', 'failure', 'cancelled', 'pending', 'unknown'] },
        },
        required: ['name', 'conclusion'],
      },
    },
    all_required_jobs_seen: { type: 'boolean', description: 'false if fewer than the 5 expected checks (test x3, pre-commit, web) ever reported' },
    failing_job: { type: 'string', description: 'name of the first/primary failing job; empty string if conclusion is success or timeout' },
    log_tail: { type: 'string', description: 'last ~60 lines of the failing job log, verbatim; empty string if conclusion is success' },
    log_path: { type: 'string', description: 'absolute path to a file you wrote containing the full failing-job log (gh run view --log-failed > <path>); empty string if conclusion is success' },
    wait_seconds: { type: 'integer', description: 'approximately how long you waited before reaching this conclusion' },
  },
  required: ['conclusion', 'jobs', 'all_required_jobs_seen', 'failing_job', 'log_tail', 'log_path', 'wait_seconds'],
}

const LAND_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ci_green: { type: 'boolean', description: 'true only if every one of the 5 expected checks (test x3, pre-commit, web) concluded success — re-verify with gh pr checks, do not trust the Watch phase blindly' },
    review_verdict_clean: { type: 'boolean', description: 'true only if the accuracy-review verdict handed to this workflow (or re-checked via accuracy_board.py / PR comments) is "mergeable" with no MUST-FIX findings' },
    base_is_develop: { type: 'boolean', description: 'true only if the PR base is literally "develop" — verify with gh pr view, do not assume' },
    preconditions_met: { type: 'boolean', description: 'must equal (ci_green AND review_verdict_clean AND base_is_develop) — computed, not vibes' },
    merged: { type: 'boolean', description: 'true only if preconditions_met is true and gh pr merge actually exited 0' },
    merge_command_output: { type: 'string', description: 'literal output of gh pr merge, or empty string if not attempted' },
    board_done_attempted: { type: 'boolean' },
    board_done_exit_code: { type: 'integer', description: '-1 if not attempted; 0 for success; 2 means the board correctly refused an H-numbered issue — report that as a correct outcome' },
    board_done_refused_human_issue: { type: 'boolean', description: 'true if board_done_exit_code is 2' },
    state_cleared: { type: 'boolean', description: 'true only if accuracy_board.py state set in_the_middle_of "" exited 0' },
    reason: { type: 'string', description: 'Plain statement of why merged is true or false, referencing the three precondition booleans explicitly' },
  },
  required: ['ci_green', 'review_verdict_clean', 'base_is_develop', 'preconditions_met', 'merged', 'merge_command_output', 'board_done_attempted', 'board_done_exit_code', 'board_done_refused_human_issue', 'state_cleared', 'reason'],
}

// ---------------------------------------------------------------- Open
phase('Open')

const open = await agent(`${GROUND}
TASK: Open the PR for issue #${issue}, branch ${branch} -> ${base}. Do this in order:
1. git -C ${ROOT} fetch origin. Confirm the branch exists (git -C ${ROOT} rev-parse --verify ${branch}) and is ahead of base: git -C ${ROOT} rev-list --count origin/${base}..${branch}. If 0, stop — there is nothing to land — set opened=false and say so in blockers.
2. Push it: git -C ${ROOT} push -u origin ${branch}.
3. Write the PR body to a file (do NOT put it inline on the command line): gather the issue title (gh issue view ${issue} --repo LemelyIG/Lemely --json title,body), the commits on this branch (git -C ${ROOT} log origin/${base}..${branch} --oneline), and — if the caller context above carries a plan, gate results, or an accuracy-review verdict — summarise them. The body MUST contain the literal line "Closes #${issue}", a short plan/what-changed summary, the evidence (tests run, gates passed), and the accuracy-review verdict (or "no review verdict was supplied to this workflow" if none was). Write it with a heredoc to an absolute path (e.g. ${ROOT}/.pr-body-${issue}.md or /tmp/pr-body-${issue}.md) and record that path in body_file_path.
4. Open the PR: gh pr create --repo LemelyIG/Lemely --base ${base} --head ${branch} --title "<conventional-commit-style title> (#${issue})" --body-file <the file from step 3>. Capture the PR number and URL from its output (gh pr create prints the URL; get the number with gh pr view ${branch} --repo LemelyIG/Lemely --json number,url if needed).
5. Link it on the board: from ${ROOT}, python scripts/accuracy_board.py review ${issue} --pr <pr_url>. This is the ONLY sanctioned way to set the issue to In review — never touch the board via raw gh api graphql.
Return per the schema. opened=true only if gh pr create succeeded and you have a real pr_number and pr_url.`,
  { label: `open-${issue}`, phase: 'Open', model: 'sonnet', schema: OPEN_SCHEMA })

if (!open) {
  log(`accuracy-pr-land: open agent died for #${issue}; aborting before any further action.`)
  return { ok: false, error: 'open-agent-died', issue, branch, base }
}
if (!open.opened || !open.pr_number) {
  log(`accuracy-pr-land: PR did not open for #${issue}: ${open.blockers.join(' | ')}`)
  return { ok: false, error: 'pr-not-opened', issue, branch, base, open }
}
log(`accuracy-pr-land: PR #${open.pr_number} opened (${open.pr_url}) for issue #${issue}`)

// ---------------------------------------------------------------- Watch
phase('Watch')

const watch = await agent(`${GROUND}
TASK: Watch CI to conclusion for PR #${open.pr_number} (${open.pr_url}), branch ${branch}. Read-only: never edit, never push, never re-run a job to "try again" without understanding why it failed.
1. Poll with: gh pr checks ${open.pr_number} --repo LemelyIG/Lemely --watch --interval 30 — wrap it with a sane cap (e.g. 'timeout 2700 gh pr checks ${open.pr_number} --repo LemelyIG/Lemely --watch --interval 30'; adjust if this repo's CI is known to run longer, but never wait unboundedly). If the command itself times out (exit 124) or you otherwise give up waiting, set conclusion='timeout' — NEVER report a timeout as success or as failure.
2. Once settled, enumerate every check with: gh pr checks ${open.pr_number} --repo LemelyIG/Lemely (no --watch) and gh run list --repo LemelyIG/Lemely --branch ${branch} --limit 5. Expect 5 checks: test (3.12), test (3.13), test (3.14), pre-commit, web. Set all_required_jobs_seen=false if fewer ever reported.
3. If anything failed: identify the failing job, then gh run view <run-id> --repo LemelyIG/Lemely --log-failed to get the failing output. Write the FULL failing log to an absolute file path (e.g. /tmp/pr-${open.pr_number}-fail.log) and record it as log_path. Put the last ~60 lines, verbatim, in log_tail.
4. conclusion='success' only if every one of the 5 checks concluded success. conclusion='failure' if any concluded failure (even if others are still pending — pick the clearest failing job). conclusion='timeout' if you gave up waiting before every check settled.
Return per the schema.`,
  { label: `watch-${issue}`, phase: 'Watch', model: 'sonnet', schema: WATCH_SCHEMA })

if (!watch) {
  log(`accuracy-pr-land: watch agent died for #${issue}/PR #${open.pr_number}; treating CI as unresolved (not a pass).`)
}

// ---------------------------------------------------------------- Triage (conditional)
let triage = null
if (watch && watch.conclusion === 'failure') {
  phase('Triage')
  log(`accuracy-pr-land: CI red on PR #${open.pr_number} (job: ${watch.failing_job || 'unknown'}). Calling accuracy-gate-triage — not reimplementing triage here.`)
  try {
    // accuracy-gate-triage requires at least one of gate/log_path and returns
    // 'missing-args' if both are empty — which would make triage silently not happen on
    // exactly the runs that most need it. Fall back to a named gate so it always has a
    // handle, and forward ROOT so triage diagnoses the tree this PR was built in.
    const triageGate = watch.failing_job || (watch.log_path ? '' : `ci (PR #${open.pr_number}, job unattributed)`)
    triage = await workflow('accuracy-gate-triage', { gate: triageGate, log_path: watch.log_path || '', issue, root: ROOT })
    log(`accuracy-pr-land: accuracy-gate-triage returned ok=${triage ? triage.ok : 'null'}${triage && triage.root_cause ? `, root_cause=${triage.root_cause}` : ''}`)
  } catch (e) {
    const detail = e && e.message ? e.message : String(e)
    log(`accuracy-pr-land: accuracy-gate-triage threw: ${detail}. Degrading to a reported failure, not killing this run.`)
    triage = { ok: false, error: 'triage-workflow-threw', detail }
  }
} else if (watch && watch.conclusion !== 'success') {
  log(`accuracy-pr-land: CI conclusion is '${watch.conclusion}' (not success, not failure) — skipping triage, this run will not merge.`)
}

if (watch && watch.conclusion !== 'success') {
  // CI is not green: never proceed to a merge decision. Report and stop.
  return {
    ok: true,
    pr_number: open.pr_number,
    pr_url: open.pr_url,
    ci: watch,
    triage,
    merged: false,
    reason: watch.conclusion === 'timeout'
      ? `CI did not settle within the watch window; reported as timeout, not a pass. Re-run Watch (or investigate ${open.pr_url} directly) before landing.`
      : `CI is red on job '${watch.failing_job || 'unknown'}'. ${triage && triage.ok ? `Triage root cause: ${triage.root_cause} (fix_target=${triage.fix_target}).` : 'Triage did not produce a usable conclusion — see the triage field.'} Not merged.`,
  }
}
if (!watch) {
  return { ok: false, error: 'watch-agent-died', issue, pr_number: open.pr_number, pr_url: open.pr_url, merged: false, reason: 'watch agent died; CI status unknown, refusing to merge blind' }
}

// ---------------------------------------------------------------- Land
phase('Land')

const land = await agent(`${GROUND}
TASK: You are the final decision stage for landing PR #${open.pr_number} (${open.pr_url}), issue #${issue}, branch ${branch} -> ${base}. You decide whether to merge; you do not merge on vibes — every precondition must be an explicit, independently-verified boolean.

WATCH-PHASE CI REPORT (re-verify, do not just trust it): ${JSON.stringify(watch)}
TRIAGE (only present if CI was red before this point — if present and non-null, CI was NOT clean and you must not treat this PR as ready): ${JSON.stringify(triage)}
CALLER CONTEXT (may carry the accuracy-review verdict from accuracy-issue-execute): ${JSON.stringify(args)}

Steps:
1. Re-verify CI yourself: gh pr checks ${open.pr_number} --repo LemelyIG/Lemely. Set ci_green=true only if every one of the 5 checks (test x3, pre-commit, web) shows success right now.
2. Determine the accuracy-review verdict: prefer the one in CALLER CONTEXT if present (verdict must be exactly "mergeable" with zero MUST-FIX findings); otherwise look for it on the PR (gh pr view ${open.pr_number} --repo LemelyIG/Lemely --json comments,reviews) or state plainly that none was supplied. If no clean review verdict can be established, review_verdict_clean=false.
3. Verify the PR base is exactly 'develop': gh pr view ${open.pr_number} --repo LemelyIG/Lemely --json baseRefName. base_is_develop=true only if that value is literally "develop". If it is anything else (especially "main"), set base_is_develop=false and DO NOT merge under any circumstance — this workflow may only merge feature -> develop.
4. Compute preconditions_met = ci_green AND review_verdict_clean AND base_is_develop. This is arithmetic, not judgment — do not set it true unless all three booleans are true.
5. If and only if preconditions_met: gh pr merge ${open.pr_number} --repo LemelyIG/Lemely --squash --delete-branch. Capture its literal output. Set merged=true only if the command exited 0.
6. If merged: from ${ROOT}, run 'python scripts/accuracy_board.py done ${issue}'. If it exits 0, board_done_exit_code=0. If it exits 2, that means the board correctly refused an H-numbered issue — report board_done_exit_code=2 and board_done_refused_human_issue=true; this is a CORRECT outcome, not a failure, but it means the issue did NOT actually get marked Done and you should say so in reason (this should not happen for a normal issue that reached this point; flag it prominently if it does). Then 'python scripts/accuracy_board.py state set in_the_middle_of ""' and set state_cleared=true only if that exited 0.
7. If preconditions_met is false: do NOT merge, do NOT call accuracy_board.py done. Leave board_done_attempted=false, board_done_exit_code=-1.
Return per the schema, with reason explicitly citing which of ci_green/review_verdict_clean/base_is_develop was false if you did not merge.`,
  { label: `land-${issue}`, phase: 'Land', schema: LAND_SCHEMA })

if (!land) {
  log(`accuracy-pr-land: land agent died for #${issue}/PR #${open.pr_number}. No merge decision was made — treat as NOT merged and inspect ${open.pr_url} by hand.`)
  return { ok: false, error: 'land-agent-died', issue, pr_number: open.pr_number, pr_url: open.pr_url, ci: watch, merged: false, reason: 'land agent died before a merge decision was reached' }
}

// Defensive cross-check: never trust an agent-reported merged=true that contradicts its own
// reported preconditions — this is the "cannot merge on vibes" guarantee enforced twice.
const preconditionsActuallyMet = land.ci_green === true && land.review_verdict_clean === true && land.base_is_develop === true
const merged = land.merged === true && preconditionsActuallyMet
if (land.merged === true && !preconditionsActuallyMet) {
  log(`accuracy-pr-land: INCONSISTENCY — land agent reported merged=true but preconditions were not all true (ci_green=${land.ci_green}, review_verdict_clean=${land.review_verdict_clean}, base_is_develop=${land.base_is_develop}). Overriding merged to false in the report; investigate PR #${open.pr_number} by hand.`)
}

log(`accuracy-pr-land: #${issue} PR #${open.pr_number} — merged=${merged}. ${land.reason}`)

return {
  ok: true,
  pr_number: open.pr_number,
  pr_url: open.pr_url,
  ci: watch,
  triage,
  merged,
  reason: merged ? land.reason : `${land.reason}${land.merged === true && !preconditionsActuallyMet ? ' [overridden: agent claimed merged with unmet preconditions]' : ''}`,
  board_done_exit_code: land.board_done_exit_code,
  board_done_refused_human_issue: land.board_done_refused_human_issue,
}
