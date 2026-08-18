export const meta = {
  name: 'accuracy-issue-execute',
  description: 'Implement one accuracy-programme GitHub issue end to end: scope, TDD implement, verify gates + adversarial review, opus verdict. Does NOT open the PR.',
  phases: [
    { title: 'Scope', detail: 'One sonnet agent reads the issue, the spec section, and the code (tokensave) and returns a structured plan' },
    { title: 'Implement', detail: 'One sonnet accuracy-implementer executes the plan TDD-style and commits (signed, conventional) after pre-commit passes' },
    { title: 'Verify', detail: 'Parallel: real gate suite (pre-commit, ruff, mypy, lint-imports, pytest) + adversarial accuracy-reviewer on the diff' },
    { title: 'Decide', detail: 'One opus agent reads plan, gates, and review; returns {ready_for_pr, blocking, next_action}. The orchestrator opens the PR, not this workflow' },
  ],
}

// ---------------------------------------------------------------- args guard
if (!args || args.issue === undefined || args.issue === null || args.issue === '') {
  log('accuracy-issue-execute: missing required argument. Call as workflow("accuracy-issue-execute", { issue: <number>, root: <optional absolute path, defaults to /home/sico/Lemely-worktrees/accuracy> }).')
  return { ok: false, error: 'missing-args', detail: 'args.issue is required, e.g. { issue: 25 }' }
}
const issue = Number(args.issue)
if (!Number.isInteger(issue) || issue <= 0) {
  log(`accuracy-issue-execute: args.issue must be a positive integer GitHub issue number, got: ${JSON.stringify(args.issue)}`)
  return { ok: false, error: 'bad-issue-arg', detail: `unparseable issue number: ${JSON.stringify(args.issue)}` }
}

// Human-only issues: an agent must never implement, close, or work around these.
// This is every H-numbered issue in the tracker (H1..H10 as of writing) — verify with:
//   gh issue list --repo LemelyIG/Lemely --state all --json number,title | grep -E '"title": *"H[0-9]'
const HUMAN_ISSUES = [34, 48, 49, 50, 51, 52, 55, 60]
// Already-closed issues: never reopen, never re-implement.
const CLOSED_ISSUES = [34, 42, 48, 50, 60]
if (HUMAN_ISSUES.includes(issue)) {
  log(`accuracy-issue-execute: #${issue} is an H (human-only) issue. Refusing to touch it. Block and wait for the human.`)
  return { ok: false, error: 'human-only-issue', issue, detail: 'H-numbered issues are human tasks; an agent must block, not work around them.' }
}
if (CLOSED_ISSUES.includes(issue)) {
  log(`accuracy-issue-execute: #${issue} is already closed. Refusing to re-implement or reopen it.`)
  return { ok: false, error: 'already-closed-issue', issue, detail: 'Issue is closed; nothing to execute.' }
}

const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} — run every command from this directory (absolute paths only; your cwd resets between bash calls).
Repo: github.com/LemelyIG/Lemely. Python venv at ${ROOT}/.venv — activate with 'source ${ROOT}/.venv/bin/activate'.
If ${ROOT} is a worktree and ${ROOT}/.venv does not exist, bootstrap it first: cd ${ROOT} && python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]" — the main repo's venv (at /home/sico/Lemely) editable-installs lemely from /home/sico/Lemely, so a worktree without its own venv silently imports the wrong branch. Never reuse the main repo's .venv from ${ROOT}.

THE SPEC lives on main, not necessarily on your branch. Read it with:
  git -C ${ROOT} show origin/main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md
Sections: 1 Terminology, 2 Verification pass, 3 Architecture (lemely/eval record model), 4 Milestones M0-M4, 5 Review budget, 6 Labelling protocol, 7 Sequencing constraints, 8 Cost and budget, 9 Execution mechanics, 10 Failure modes, 11 Human tasks, 12 Changes.

STANDING RULES (non-negotiable):
- Signed commits only: 'git commit -S'. Conventional messages with scopes (feat(det):, fix(parsers_det):, refactor(core):, test(accuracy):, feat(eval):) and the issue number in the message, e.g. "feat(eval): add EvalRecord model (#25)".
- 'pre-commit run --all-files' must pass, with every failure fixed, BEFORE any commit is created.
- Never push. Never open a PR. Never close or reopen any GitHub issue. H-numbered issues (#34 #48 #49 #50 #51 #52 #55 #60) are human-only: never mark done, never work around — block and report.
- Never weaken a gate to get green: no loosened thresholds, no deleted assertions, no skip/xfail, no widened tolerances, no narrowed denominators. The review-budget ratchet is review_rate_signal <= 8%, review_rate_total <= 10%, per-paper p95 <= 15%, CI fails when review_rate > min(10%, last_merged_review_rate).
- GEMINI_API_KEY lives in the environment only — never in lemely.toml, never committed. Both cost ceilings are PRE-FLIGHT checks, not hard stops.
- Explore code with the tokensave MCP tools (tokensave_context, tokensave_search, tokensave_callers, tokensave_impact) — never spawn an Explore agent for code research.
- tests/fixtures/real-papers/*.pdf contains a minor's real handwritten exam scripts — never redistribute them or attach them to anything outward-facing.

SEQUENCING (spec section 7 — violating any of these is a blocking defect):
- One-commit bundles: M1.1 (#36) extraction-confidence propagation + _calibrate_confidence rebuild + paper-level grade-confidence rule is ONE commit; M1.2 (#37) positional-fallback removal + the metric's CI-target re-derivation is ONE commit.
- Strict orderings (first -> then): M0.0 -> any baseline run; M0.8 -> M0.3/M0.4; M0.2 cache-bypass seam -> M0.3; M0.2 pricing+ceiling fix -> any multi-sweep run; M0.3 -> any A/B claim; M0.9 -> M1.1; M0.7a -> M2.3/M2.4; M2.1 -> M0.7b; M2.2 -> D7 repairs in M3; M0.8 parent_id -> the ECF fix; M3/T1.3 -> unit/sig-fig enforcement; M3/T2.9 -> narrow LLM repair; M3 -> M4.
- Must NOT land together: mark-raising with mark-lowering fixes (they cancel); multiple prompt VERSION bumps (each invalidates the cached corpus); the random audit M4/T1.10 with the confidence unit M1.1.

BRANCHING: feature branches are cut from origin/develop and named feature/accuracy-<issue#>-<slug>, and that exact name comes from ONE source: the string printed by 'python scripts/accuracy_board.py start <issue>'. No agent invents a slug. develop must already contain the spec (a human fast-forwards develop to main as a launch-checklist item). Check readiness against the PUSHED refs, not local branches: git -C ${ROOT} fetch --quiet origin && git rev-list --count origin/develop..origin/main — this must equal 0. If it is nonzero, develop has NOT been fast-forwarded: STOP and report the blocker instead of cutting from main or from a stale develop.

BOARD: scripts/accuracy_board.py is the ONLY sanctioned interface to GitHub issues and the project board (it carries the H-issue guard). Never call 'gh api graphql' to mutate the board. Subcommands you need here: 'accuracy_board.py start <issue>' (sets In progress, comments, PRINTS THE BRANCH NAME), 'accuracy_board.py state set <key> <value>'.
`

// ---------------------------------------------------------------- schemas
const PLAN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    issue: { type: 'integer' },
    title: { type: 'string' },
    state: { type: 'string', enum: ['open', 'closed'], description: 'GitHub issue state as reported by gh issue view' },
    is_human_issue: { type: 'boolean', description: 'true if the issue is an H-numbered human task' },
    ready: { type: 'boolean', description: 'false if any spec-section-7 predecessor has not landed on the base branch, or the issue is closed or human-only' },
    blocked_by: { type: 'array', items: { type: 'string' }, description: 'Unmet predecessors, each as "issue/milestone: what is missing", empty if ready' },
    branch_name: { type: 'string', description: 'ADVISORY ONLY, not authoritative: your best guess at feature/accuracy-<issue#>-<slug> for planning purposes. The real branch name is decided by scripts/accuracy_board.py start <issue> in the Implement phase — never invent a slug for the actual branch.' },
    spec_sections: { type: 'array', items: { type: 'string' }, description: 'Spec sections read for this plan, e.g. "4 M0.1", "7"' },
    acceptance_criteria: { type: 'array', items: { type: 'string' }, description: 'The issue/spec acceptance criteria restated concretely and testably' },
    files_to_change: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', description: 'Repo-relative path' },
          change: { type: 'string', description: 'What changes in this file and why' },
        },
        required: ['path', 'change'],
      },
    },
    tests_to_add: { type: 'array', items: { type: 'string' }, description: 'Each entry: test file path + what behaviour it asserts + why it fails before the fix (for M1 regression tests)' },
    sequencing_constraints: { type: 'array', items: { type: 'string' }, description: 'The spec-section-7 constraints that apply to THIS issue, verbatim enough to enforce' },
    one_commit_bundle: { type: 'boolean', description: 'true if this issue is one of the must-ship-as-one-commit bundles (M1.1 or M1.2)' },
    one_commit_bundle_detail: { type: 'string', description: 'If one_commit_bundle, exactly which pieces must land in the single commit; empty string otherwise' },
    commit_message_prefix: { type: 'string', description: 'Conventional-commit type(scope) prefix to use, e.g. "feat(eval)"' },
    risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['issue', 'title', 'state', 'is_human_issue', 'ready', 'blocked_by', 'branch_name', 'spec_sections', 'acceptance_criteria', 'files_to_change', 'tests_to_add', 'sequencing_constraints', 'one_commit_bundle', 'one_commit_bundle_detail', 'commit_message_prefix', 'risks'],
}

const IMPL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    completed: { type: 'boolean', description: 'true only if every plan item is implemented, pre-commit passed, and the commits exist' },
    branch: { type: 'string', description: 'The branch the commits are on' },
    commits: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          sha: { type: 'string', description: 'Full 40-char sha from git rev-parse' },
          message: { type: 'string', description: 'First line of the commit message' },
        },
        required: ['sha', 'message'],
      },
    },
    tests_added: { type: 'array', items: { type: 'string' }, description: 'Test file paths actually added or modified' },
    pre_commit_passed: { type: 'boolean' },
    summary: { type: 'string', description: 'What was implemented, deviations from the plan and why' },
    blockers: { type: 'array', items: { type: 'string' }, description: 'Anything that stopped the work; empty if completed' },
  },
  required: ['completed', 'branch', 'commits', 'tests_added', 'pre_commit_passed', 'summary', 'blockers'],
}

const GATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    all_passed: { type: 'boolean' },
    tree_clean: { type: 'boolean', description: 'git status --porcelain is empty after the run (pre-commit auto-fixes count as failure)' },
    results: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          command: { type: 'string' },
          exit_code: { type: 'integer' },
          output_tail: { type: 'string', description: 'Last ~30 lines of literal output, verbatim' },
        },
        required: ['command', 'exit_code', 'output_tail'],
      },
    },
  },
  required: ['all_passed', 'tree_clean', 'results'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['mergeable', 'blocked'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['MUST-FIX', 'SHOULD-FIX', 'NIT'] },
          summary: { type: 'string' },
          file: { type: 'string', description: 'file:line where possible, or "diff-wide"' },
          detail: { type: 'string', description: 'The spec clause or hunt-list item violated, and a concrete fix' },
        },
        required: ['severity', 'summary', 'file', 'detail'],
      },
    },
    checks_performed: { type: 'array', items: { type: 'string' }, description: 'What was checked and how (ran code vs read code), even when no finding resulted' },
  },
  required: ['verdict', 'findings', 'checks_performed'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ready_for_pr: { type: 'boolean' },
    blocking: { type: 'array', items: { type: 'string' }, description: 'Every reason this cannot go to PR yet; empty if ready_for_pr' },
    next_action: { type: 'string', description: 'The single concrete next step for the orchestrator (open the PR against develop / send back to implementer with these fixes / block on human issue #N)' },
    rationale: { type: 'string', description: 'How the gates, the review, and the plan acceptance criteria support the verdict' },
  },
  required: ['ready_for_pr', 'blocking', 'next_action', 'rationale'],
}

// ---------------------------------------------------------------- Scope
phase('Scope')

const plan = await agent(`${GROUND}
TASK: Produce the implementation plan for GitHub issue #${issue}. Plan only — change NOTHING, run only read-only commands.
1. Read the issue: gh issue view ${issue} --repo LemelyIG/Lemely --json number,title,state,body,labels && gh issue view ${issue} --repo LemelyIG/Lemely --comments
2. Read the spec section(s) the issue names (git show main:... as above), plus section 7 in full.
3. Explore the code the issue touches with tokensave_context / tokensave_search / tokensave_callers. Confirm current behaviour with Read/grep where exact lines matter.
4. Check readiness: for each section-7 predecessor of this issue, verify on origin/develop whether it has landed (look for its code/tests, check the issue tracker state with gh). If a predecessor is missing, set ready=false and name it in blocked_by.
5. Decide the conventional-commit prefix. Do NOT invent the branch name — branch_name here is advisory only; the actual branch is obtained in the Implement phase from 'scripts/accuracy_board.py start ${issue}'.
Return the plan exactly per the schema. Restate acceptance criteria concretely: each one must be checkable by a command or a test. If the issue is one of the one-commit bundles (M1.1/#36, M1.2/#37), say so and enumerate the pieces that must not be split.`,
  { label: `scope-${issue}`, phase: 'Scope', model: 'sonnet', schema: PLAN_SCHEMA })

if (!plan) {
  log(`accuracy-issue-execute: scope agent died for #${issue}; aborting before any mutation.`)
  return { ok: false, error: 'scope-agent-died', issue }
}
if (plan.is_human_issue) {
  log(`accuracy-issue-execute: scope determined #${issue} is a human-only issue. Aborting.`)
  return { ok: false, error: 'human-only-issue', issue, plan }
}
if (plan.state === 'closed') {
  log(`accuracy-issue-execute: #${issue} is closed on GitHub. Aborting.`)
  return { ok: false, error: 'already-closed-issue', issue, plan }
}
if (!plan.ready) {
  log(`accuracy-issue-execute: #${issue} is blocked by: ${plan.blocked_by.join(' | ')}. Aborting without changes.`)
  return { ok: false, error: 'blocked-by-sequencing', issue, plan }
}

// ---------------------------------------------------------------- Implement
phase('Implement')

const impl = await agent(`${GROUND}
TASK: Implement GitHub issue #${issue} exactly per the approved plan below. TDD, strictly: write the failing test first, watch it fail for the stated reason, then implement, then watch it pass.

APPROVED PLAN:
${JSON.stringify(plan, null, 2)}

Mechanics:
1. Verify the pushed-ref precondition (command in the ground rules) holds. If not, STOP: return completed=false with the blocker "develop not fast-forwarded to main".
2. Obtain the branch name from the board, not by inventing one: from ${ROOT}, run 'python scripts/accuracy_board.py start ${issue}' and use EXACTLY the branch name it prints (it also sets the issue to In progress and comments — that is the sanctioned way to touch GitHub issue state here, never raw 'gh api graphql'). git -C ${ROOT} fetch origin. If the current branch is already that branch name, continue on it; otherwise create it: git -C ${ROOT} checkout -b <branch-name-from-board> origin/develop. Never work on main or develop directly. Put the exact printed branch name in the 'branch' field of your report and record it: 'python scripts/accuracy_board.py state set branch <branch-name>' and 'python scripts/accuracy_board.py state set in_the_middle_of "implementing #${issue}"'.
3. Implement per the plan. Stay inside the plan's files_to_change scope; if reality forces a deviation, record it in your summary.
4. Before EVERY commit: source ${ROOT}/.venv/bin/activate && cd ${ROOT} && pre-commit run --all-files — fix all failures, re-run until clean.
5. Commit signed and conventional: git -C ${ROOT} commit -S -m "${plan.commit_message_prefix}: <subject> (#${issue})". ${plan.one_commit_bundle ? 'THIS ISSUE IS A ONE-COMMIT BUNDLE: all of the following must land in a SINGLE commit, never split: ' + plan.one_commit_bundle_detail : 'Small, coherent commits are fine, but never mix mark-raising with mark-lowering changes and never bump more than one prompt VERSION.'}
6. Do NOT push, do NOT open a PR, do NOT close or reopen the issue, do NOT call raw 'gh api graphql' board mutations. Once your commits exist, clear the in-progress marker: 'python scripts/accuracy_board.py state set in_the_middle_of ""'.
Return per the schema, with full shas from git rev-parse.`,
  { label: `implement-${issue}`, phase: 'Implement', model: 'sonnet', agentType: 'accuracy-implementer', schema: IMPL_SCHEMA })

if (!impl) {
  log(`accuracy-issue-execute: implementer died for #${issue}. The tree at ${ROOT} may be dirty — inspect before retrying.`)
  return { ok: false, error: 'implementer-died', issue, plan }
}
if (!impl.completed) {
  log(`accuracy-issue-execute: implementer did not complete #${issue}: ${impl.blockers.join(' | ')}`)
  return { ok: false, error: 'implementation-blocked', issue, plan, impl }
}

// ---------------------------------------------------------------- Verify
phase('Verify')

const [gates, review] = await parallel([
  () => agent(`${GROUND}
TASK: Run the real gate suite on branch ${impl.branch} at ${ROOT} and report literal results. Run commands, fix NOTHING, change NOTHING.
Run, in order, each from an activated venv (source ${ROOT}/.venv/bin/activate && cd ${ROOT}):
1. pre-commit run --all-files
2. ruff check .
3. ruff format --check .
4. mypy lemely
5. lint-imports
6. pytest -q
Then: git -C ${ROOT} status --porcelain (must be empty — if pre-commit auto-fixed anything, the tree is dirty and all_passed=false).
Record every command with its literal exit code and the last ~30 lines of output, verbatim. all_passed=true only if every exit code is 0 AND the tree is clean. Do not summarise away failures.`,
    { label: `gates-${issue}`, phase: 'Verify', model: 'sonnet', schema: GATE_SCHEMA }),
  () => agent(`${GROUND}
TASK: Adversarially review the diff for issue #${issue} on branch ${impl.branch} before a PR opens. Read-only: never edit the diff yourself.
The diff: git -C ${ROOT} diff origin/develop...${impl.branch} ; commits: git -C ${ROOT} log origin/develop..${impl.branch} --oneline
The plan it claims to implement:
${JSON.stringify(plan, null, 2)}
Assume every claim is false until the code proves it. Hunt in priority order: gates weakened to pass; denominators narrowed (the D18 shape); targets moved instead of met; mark-raising mixed with mark-lowering; multiple prompt VERSION bumps; hardcoded values masquerading as computed; tests asserting the implementation instead of the behaviour (an M1 regression test must demonstrably fail on pre-fix code — check out the parent commit and run it if needed, then return to ${impl.branch}); one-commit bundles split. Verify each acceptance criterion in the plan is actually met by the diff, not merely claimed.
Report per the schema: verdict 'blocked' if any MUST-FIX exists.`,
    { label: `review-${issue}`, phase: 'Verify', agentType: 'accuracy-reviewer', schema: REVIEW_SCHEMA }),
])

if (!gates) log(`accuracy-issue-execute: gate agent died for #${issue}; treating gates as failed.`)
if (!review) log(`accuracy-issue-execute: review agent died for #${issue}; treating review as blocked.`)

// ---------------------------------------------------------------- Decide
phase('Decide')

const verdict = await agent(`${GROUND}
TASK: You are the final decision stage for issue #${issue} on branch ${impl.branch}. Decide whether this work is ready for the orchestrator to open a PR against develop. You do NOT open the PR yourself — a human stays in the loop on anything outward-facing.

THE PLAN:
${JSON.stringify(plan, null, 2)}

IMPLEMENTER REPORT:
${JSON.stringify(impl, null, 2)}

GATE RESULTS (null means the gate agent died — treat as failed):
${JSON.stringify(gates, null, 2)}

ADVERSARIAL REVIEW (null means the reviewer died — treat as blocked):
${JSON.stringify(review, null, 2)}

Rules for the verdict:
- ready_for_pr=false if any gate failed, the tree is dirty, any MUST-FIX finding stands, any acceptance criterion is unmet, a one-commit bundle was split, or any section-7 constraint was violated.
- SHOULD-FIX and NIT findings do not block by themselves: mention them in rationale so the orchestrator can carry them into the PR description. blocking[] holds ONLY true blockers.
- You may run read-only commands at ${ROOT} to spot-check any claim you doubt (git log/diff/show, pytest on a single test, grep). Prefer checking over trusting.
- next_action must be one concrete instruction: "open PR from ${impl.branch} into develop titled '...'", or "re-run implement with these fixes: ...", or "block on #N".
Return per the schema.`,
  { label: `decide-${issue}`, phase: 'Decide', schema: VERDICT_SCHEMA })

if (!verdict) {
  log(`accuracy-issue-execute: decide agent died for #${issue}. Returning without a verdict — do NOT open a PR.`)
  return { ok: false, error: 'decide-agent-died', issue, branch: impl.branch, commits: impl.commits, gates, review }
}

return {
  ok: true,
  issue,
  branch: impl.branch,
  commits: impl.commits,
  verdict,
  gates_passed: gates ? gates.all_passed : false,
  review_verdict: review ? review.verdict : 'blocked',
  plan_acceptance_criteria: plan.acceptance_criteria,
}
