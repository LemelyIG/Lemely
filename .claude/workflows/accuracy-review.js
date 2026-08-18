export const meta = {
  name: 'accuracy-review',
  description: 'Adversarial multi-dimension review of a diff before a PR opens: 6 programme-specific review dimensions, per-finding skeptic verification, opus merge recommendation.',
  phases: [
    { title: 'Review', detail: '6 sonnet reviewers pipelined over programme-specific dimensions: correctness, measurement-integrity, sequencing, test-honesty, review-budget, scope' },
    { title: 'Verify', detail: 'Per finding, 2 independent sonnet skeptics try to REFUTE it (inside the pipeline, no barrier); a finding survives only if a majority fail to refute' },
    { title: 'Report', detail: 'One opus agent synthesises surviving findings, most severe first, and returns a merge recommendation' },
  ],
}

// The harness may deliver `args` as a JSON string rather than an object. Normalise
// it before any guard reads a key off it — on a string every `args.<key>` is
// undefined, so guards either abort with "missing-args" or, worse, silently fall
// through to their defaults.
if (typeof args === 'string') {
  try { args = args.trim() ? JSON.parse(args) : {} } catch (e) { args = {} }
}
if (args === null || args === undefined) { args = {} }

// ---------------------------------------------------------------- args
const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'
const base = (args && args.base) ? String(args.base) : 'develop'
const head = (args && args.head) ? String(args.head) : 'HEAD'
const issue = (args && args.issue !== undefined && args.issue !== null && args.issue !== '') ? Number(args.issue) : null
log(`accuracy-review: reviewing ${base}...${head}${issue ? ` for issue #${issue}` : ' (no issue given)'} at ${ROOT}`)

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} (github.com/LemelyIG/Lemely). Python venv: source ${ROOT}/.venv/bin/activate. Absolute paths only — your cwd resets between bash calls.
THE DIFF UNDER REVIEW: git -C ${ROOT} diff ${base}...${head}
Its commits:            git -C ${ROOT} log ${base}..${head} --oneline
Read code at either ref without checking anything out: git -C ${ROOT} show ${head}:<path> (or ${base}:<path>).
${issue ? `The diff claims to implement issue #${issue}: gh issue view ${issue} --repo LemelyIG/Lemely --json number,title,state,body` : 'No issue number was supplied; derive intent from the commit messages and the spec.'}
THE SPEC: git -C ${ROOT} show origin/main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md (sections: 4 milestones, 5 review budget, 7 sequencing, 10 failure modes).

YOU ARE READ-ONLY in ${ROOT}: never edit, format, commit, or check out branches there. If you must RUN code at a ref (e.g. prove a regression test fails on pre-fix code), create a throwaway detached worktree OUTSIDE the repo: git -C ${ROOT} worktree add --detach /tmp/acc-review-<yourlabel> <ref>, bootstrap its own venv if tests need one (python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]"), and ALWAYS remove it afterwards: git -C ${ROOT} worktree remove --force /tmp/acc-review-<yourlabel>. Never reuse ${ROOT}'s or the main repo's (/home/sico/Lemely) .venv from that worktree — an editable install resolves imports to the wrong code.
Explore code with the tokensave MCP tools (tokensave_context, tokensave_search, tokensave_callers, tokensave_impact) — never spawn an Explore agent for code research.

PROGRAMME FACTS the review is measured against:
- Review-budget gate (spec section 5): review_rate_signal <= 8%, review_rate_total <= 10%, per-paper p95 <= 15%. It is a RATCHET: CI fails when review_rate > min(10%, last_merged_review_rate). Baseline being ratcheted down from: 19.1%.
- Any A/B improvement claim below the published A/A churn floor is noise; if no A/A floor has been published yet (M0.3/#27 open), ANY A/B claim is premature. A cached run comparing identical fingerprints returns a false zero delta.
- The 28-distinct-leaf corpus is not powered to prove improvement: M1's gate is NON-REGRESSION on the signed over/under split (alpha=0.05), McNemar reported not gated. A diff claiming "improves accuracy" from this corpus is overclaiming.
- Intervals and power calculations must collapse to DISTINCT LEAVES first, never raw records (28 leaves, not 68 records).
- The det parse path is the majority path; a change validated only on the gemini path can move every number while the product stands still.
- One-commit bundles (spec section 7): M1.1 confidence unit (propagation + _calibrate_confidence rebuild + paper-level grade-confidence rule); M1.2 positional-fallback deletion + CI-target re-derivation.
- Must NOT land together: mark-raising with mark-lowering fixes (they cancel — it has happened twice in project history); more than one prompt VERSION bump; the random audit M4/T1.10 with the confidence unit M1.1.
- Strict orderings (first -> then): M0.0 -> any baseline run; M0.8 -> M0.3/M0.4; M0.2 cache-bypass seam -> M0.3; M0.2 pricing fix -> any multi-sweep run; M0.3 -> any A/B claim; M0.9 -> M1.1; M0.7a split mechanism -> M2.3/M2.4; M2.1 -> M0.7b.
- No run may read the test split without an M0.7a authorisation token, and every read must append to the test-touch ledger.
- H-numbered issues (#34 #48 #49 #50 #51 #52 #55 #60) are human-only; a diff that closes, resolves, or works around one is a blocking defect.
- lemely/eval analyses must be pure functions over list[EvalRecord]: no I/O, no Gemini calls, no filesystem. Labels live at repo-root eval/labels/, never importable from pipeline code.
`

// ---------------------------------------------------------------- schemas
const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      maxItems: 4,
      description: 'At most 4 findings, ordered most severe first. An empty list is a real result but obliges checks_performed to say exactly what was checked.',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['MUST-FIX', 'SHOULD-FIX', 'NIT'] },
          summary: { type: 'string', description: 'One sentence: the defect, not the vibe' },
          file: { type: 'string', description: 'file:line in the diff where possible, or "diff-wide"' },
          evidence: { type: 'string', description: 'The diff hunk, command output, or spec clause that proves it — verbatim enough for a skeptic to re-check' },
          why_it_matters: { type: 'string', description: 'Which programme rule or acceptance criterion this violates' },
        },
        required: ['severity', 'summary', 'file', 'evidence', 'why_it_matters'],
      },
    },
    checks_performed: { type: 'array', items: { type: 'string' }, description: 'What was checked and how (ran vs read), including checks that found nothing' },
  },
  required: ['findings', 'checks_performed'],
}

const SKEPTIC_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    refuted: { type: 'boolean', description: 'true if the finding is wrong, misreads the diff, or cannot be substantiated. DEFAULT TO true WHEN UNCERTAIN.' },
    reasoning: { type: 'string', description: 'What you checked and what you found, with file:line or command output' },
    severity_adjustment: { type: 'string', enum: ['keep', 'downgrade', 'upgrade'], description: 'If not refuted: is the claimed severity right?' },
  },
  required: ['refuted', 'reasoning', 'severity_adjustment'],
}

const REPORT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    recommendation: { type: 'string', enum: ['merge', 'merge-with-fixes', 'block'] },
    summary: { type: 'string', description: 'Two or three sentences: what the diff does and whether it is safe to merge' },
    ordered_findings: {
      type: 'array',
      description: 'Surviving and unverified findings, most severe first',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['MUST-FIX', 'SHOULD-FIX', 'NIT'] },
          dimension: { type: 'string' },
          summary: { type: 'string' },
          file: { type: 'string' },
          verification: { type: 'string', enum: ['verified', 'unverified-budget-exhausted'] },
          required_action: { type: 'string', description: 'The concrete fix, or "none" for NITs' },
        },
        required: ['severity', 'dimension', 'summary', 'file', 'verification', 'required_action'],
      },
    },
    rationale: { type: 'string', description: 'Why this recommendation follows from the findings, including what was checked and found clean' },
  },
  required: ['recommendation', 'summary', 'ordered_findings', 'rationale'],
}

// ---------------------------------------------------------------- dimensions
const DIMENSIONS = [
  {
    name: 'correctness',
    focus: `Does the change do what the issue (or its commit messages) says it does?
Trace each claimed behaviour to the code that implements it. Check edge cases the issue's acceptance criteria imply. Check that new code is actually reachable (wired into the CLI/harness/gates, not dead). A feature that exists but is never called is a MUST-FIX.`,
  },
  {
    name: 'measurement-integrity',
    focus: `Hunt instrument corruption — the programme's defining risk:
- A gate weakened: threshold loosened, assertion deleted or made advisory, tolerance widened, test skipped/xfailed.
- A denominator quietly narrowed: exclusions added, abstentions dropped from the denominator, any filter that lets an extractor returning fewer questions score higher (the D18 shape). Demand the exclusion funnel for any rate that moved.
- A target moved instead of met: baseline redefined, CI target re-derived outside M1.2's same-commit rule, legacy numbers swapped for honest ones.
- A claimed delta below the A/A churn floor (or claimed before any floor exists), or an A/B comparison that could have hit the cache (identical params_fingerprint = false zero).
- A metric computed on a different population than the one it reports: raw records where distinct leaves are required, gemini-path-only where det is the majority path, dev split claimed but test split read.
- Hardcoded values masquerading as computed results.`,
  },
  {
    name: 'sequencing',
    focus: `Does this diff violate a spec section-7 constraint?
- Mark-raising mixed with mark-lowering changes in one diff (classify each behavioural change by its direction on awarded marks).
- More than one prompt VERSION bump.
- A strict ordering jumped: does the diff run a baseline/A-A/ablation/multi-sweep, or make an A/B claim, before its prerequisite landed on ${base}? Check the prerequisite code actually exists on ${base}, not just that its issue is closed.
- A must-ship-as-one-commit bundle split across commits (check git log ${base}..${head}: M1.1's three pieces, M1.2's two pieces).
- Work on, or closure of, an H-numbered issue.`,
  },
  {
    name: 'test-honesty',
    focus: `Are the tests honest?
- Tests that assert the implementation rather than the behaviour: mirroring internal calls, snapshotting the code's own output as truth, tautological assertions.
- M1 regression tests must fail on pre-fix code: prove it (throwaway worktree at the parent commit) or flag it unproven.
- Fixtures that encode the bug they claim to guard against, or fixtures altered to make a test pass (a fixture's maximum_mark must never change to satisfy an assertion).
- Coverage that moved without meaning: tests added that execute lines but assert nothing about the programme's acceptance criteria.
- Any weakening of existing tests to accommodate the new code.`,
  },
  {
    name: 'review-budget',
    focus: `Does this change raise review volume, and is that measured?
- Identify every change that can add a trigger to a question-level record (new gate, new escalation, widened trigger condition, new abstention route). Each one raises review_rate.
- If review volume can rise: was it measured against the two-part ratchet (review_rate_signal <= 8%, review_rate_total <= 10%, per-paper p95 <= 15%, CI fails above min(10%, last_merged_review_rate))? A recall-raising trigger landed without a before/after review_rate measurement is a MUST-FIX.
- Check the diff does not touch the ratchet's stored last_merged_review_rate or the gate arithmetic itself except where its issue explicitly says so.`,
  },
  {
    name: 'scope',
    focus: `Anything in the diff the issue did not ask for?
Enumerate every file in the diff (git diff ${base}...${head} --stat) and map each to the issue's stated scope. Flag: drive-by refactors, formatting churn in untouched-by-intent files, config changes (lemely.toml, pyproject, CI workflow, pre-commit config) the issue never mentioned, new dependencies, changes to gate/threshold files smuggled in under an unrelated issue, deletion or renaming of anything the issue does not name. Unrequested changes to .github/workflows/, supervisor.sh, or BUILD/ state files are MUST-FIX.`,
  },
]

// ---------------------------------------------------------------- Review + Verify (pipelined, no barrier between stages)
phase('Review')
phase('Verify')

// Agent budget: 6 reviewers + 1 report = 7; skeptics get the rest of the ~15 cap.
// 2 skeptics per finding => at most 4 findings get verified across the whole run.
const SKEPTIC_BUDGET = { left: 8 }
const SEV_RANK = { 'MUST-FIX': 0, 'SHOULD-FIX': 1, 'NIT': 2 }

const dimensionResults = await pipeline(
  DIMENSIONS,
  // Stage 1: review one dimension
  (prev, dim) => agent(`${GROUND}
REVIEW DIMENSION: ${dim.name}
${dim.focus}
Review ONLY this dimension — other agents own the others. Read the full diff first, then hunt. Every finding needs evidence a skeptic can independently re-check; a finding you cannot evidence is not a finding. Order findings most severe first (MUST-FIX, then SHOULD-FIX, then NIT), at most 4. If you find nothing, return an empty findings list and say in checks_performed exactly what you checked, against which rule, and how.`,
    { label: `review-${dim.name}`, phase: 'Review', model: 'sonnet', schema: FINDINGS_SCHEMA }),
  // Stage 2: skeptic verification of that dimension's findings, while other dimensions still review
  async (reviewResult, dim) => {
    if (!reviewResult) {
      log(`accuracy-review: reviewer for dimension '${dim.name}' died; dimension unreviewed.`)
      return { dimension: dim.name, reviewer_died: true, checks_performed: [], findings: [] }
    }
    const ordered = reviewResult.findings.slice().sort((a, b) => (SEV_RANK[a.severity] ?? 3) - (SEV_RANK[b.severity] ?? 3))
    const kept = []
    for (const finding of ordered) {
      if (SKEPTIC_BUDGET.left < 2) {
        log(`accuracy-review: skeptic budget exhausted — finding from '${dim.name}' kept UNVERIFIED, not dropped: [${finding.severity}] ${finding.summary}`)
        kept.push({ ...finding, dimension: dim.name, verification: 'unverified-budget-exhausted', skeptic_reasoning: [] })
        continue
      }
      SKEPTIC_BUDGET.left -= 2
      const skepticPrompt = (n) => `${GROUND}
YOU ARE SKEPTIC ${n} OF 2. Your job is to REFUTE the following review finding about the diff ${base}...${head}. Assume the reviewer is wrong until the evidence forces you to agree. Independently re-derive it: read the actual diff hunks, read the surrounding code at ${head}, re-run any command the evidence cites. Ways findings die: the evidence misreads the diff; the cited line does not do what is claimed; the "violated" rule does not apply to this change; the behaviour is explicitly permitted by the issue or spec; the defect exists but was already present on ${base} (pre-existing, not introduced — refuted as a finding on THIS diff). DEFAULT TO refuted=true WHEN UNCERTAIN: only a finding you have positively confirmed survives you.

THE FINDING (dimension: ${dim.name}):
${JSON.stringify(finding, null, 2)}`
      const verdicts = await parallel([
        () => agent(skepticPrompt(1), { label: `skeptic1-${dim.name}`, phase: 'Verify', model: 'sonnet', schema: SKEPTIC_SCHEMA }),
        () => agent(skepticPrompt(2), { label: `skeptic2-${dim.name}`, phase: 'Verify', model: 'sonnet', schema: SKEPTIC_SCHEMA }),
      ])
      // A dead skeptic counts as a refutation (uncertainty defaults to refuted).
      const notRefuted = verdicts.filter(v => v && v.refuted === false).length
      if (notRefuted > verdicts.length / 2) {
        kept.push({ ...finding, dimension: dim.name, verification: 'verified', skeptic_reasoning: verdicts.filter(Boolean).map(v => v.reasoning) })
      } else {
        log(`accuracy-review: finding refuted (${notRefuted}/${verdicts.length} skeptics failed to refute) — dropped: [${finding.severity}] ${dim.name}: ${finding.summary}`)
      }
    }
    return { dimension: dim.name, reviewer_died: false, checks_performed: reviewResult.checks_performed, findings: kept }
  },
)

const surviving = dimensionResults.filter(Boolean)
const allFindings = surviving.flatMap(d => d.findings)
const deadDimensions = DIMENSIONS.map(d => d.name).filter(n => !surviving.some(s => s.dimension === n && !s.reviewer_died))
log(`accuracy-review: ${allFindings.length} finding(s) survived verification across ${surviving.length}/6 dimensions${deadDimensions.length ? `; UNREVIEWED dimensions: ${deadDimensions.join(', ')}` : ''}.`)

// ---------------------------------------------------------------- Report
phase('Report')

const report = await agent(`${GROUND}
TASK: You are the final synthesis stage of the pre-PR adversarial review of ${base}...${head}${issue ? ` for issue #${issue}` : ''}. Produce the merge recommendation.

DIMENSION RESULTS (each finding here already survived skeptic verification, except those marked verification='unverified-budget-exhausted', which no skeptic checked — weigh those on their evidence, spot-checking yourself where it matters):
${JSON.stringify(surviving, null, 2)}

DIMENSIONS WITH NO RESULT (reviewer died — the diff is UNREVIEWED on these; say so, and treat a dead 'measurement-integrity' or 'sequencing' dimension as itself a reason not to recommend 'merge'):
${JSON.stringify(deadDimensions)}

Rules:
- 'block' if any verified MUST-FIX stands, or an unverified MUST-FIX survives your own spot-check, or a critical dimension went unreviewed.
- 'merge-with-fixes' when only SHOULD-FIX items stand and each has a concrete required_action.
- 'merge' only when nothing blocking stands AND the checks_performed across dimensions actually cover the diff (an empty finding list from a reviewer who checked nothing specific is not evidence of cleanliness).
- Order ordered_findings most severe first. Never invent findings; never drop one — every finding above appears in ordered_findings with its verification status.
- You may run read-only commands (git diff/show/log, gh issue view, grep) to resolve doubts before deciding.
Return per the schema. The orchestrator, not you, acts on the recommendation.`,
  { label: 'report', phase: 'Report', schema: REPORT_SCHEMA })

if (!report) {
  log('accuracy-review: report agent died. Returning raw surviving findings with recommendation "block" — never merge on a missing synthesis.')
  return { ok: false, error: 'report-agent-died', base, head, issue, recommendation: 'block', findings: allFindings, unreviewed_dimensions: deadDimensions }
}

return { ok: true, base, head, issue, recommendation: report.recommendation, report, unreviewed_dimensions: deadDimensions }
