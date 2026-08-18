export const meta = {
  name: 'accuracy-gate-triage',
  description: 'Diagnose a red gate or failing CI job fast: reproduce it literally, race three rival root-cause hypotheses from different angles, run their falsifying experiments, and have opus name the cause AND answer the defining question — fix the code, or change the gate, and if the gate, is that legitimate or moving the goalposts?',
  phases: [
    { title: 'Reproduce', detail: 'One sonnet agent reproduces the failure locally and captures the literal output; a clean non-reproduction is itself the finding' },
    { title: 'Hypothesise', detail: 'Three parallel sonnet agents, one angle each — the change under test, the gate’s own definition, the environment/fixtures — each with a concrete falsifying experiment' },
    { title: 'Test', detail: 'Pipeline over the hypotheses: run each falsifying experiment and record what it actually showed' },
    { title: 'Conclude', detail: 'One opus agent names the root cause, the fix, and answers code-vs-gate explicitly — with a legitimacy verdict if the answer is the gate' },
  ],
}

// ---------------------------------------------------------------- args guard
const gate = (args && args.gate !== undefined && args.gate !== null) ? String(args.gate) : ''
const logPath = (args && args.log_path !== undefined && args.log_path !== null) ? String(args.log_path) : ''
const issue = (args && args.issue !== undefined && args.issue !== null && args.issue !== '') ? Number(args.issue) : null

if (gate === '' && logPath === '') {
  log("accuracy-gate-triage: need something to triage. Call as workflow('accuracy-gate-triage', { gate: '<gate/check name, e.g. review-rate-ratchet, pytest, mypy, pre-commit>', log_path: '<absolute path to the failing log, optional>', issue: <related issue number, optional> }).")
  return { ok: false, error: 'missing-args', detail: 'at least one of args.gate or args.log_path is required' }
}
if (issue !== null && (!Number.isInteger(issue) || issue <= 0)) {
  log(`accuracy-gate-triage: ignoring unparseable args.issue ${JSON.stringify(args.issue)} — proceeding without an issue reference.`)
}
const issueRef = (issue !== null && Number.isInteger(issue) && issue > 0) ? issue : null
const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'

log(`accuracy-gate-triage: triaging${gate ? ` gate '${gate}'` : ''}${logPath ? ` with log ${logPath}` : ''}${issueRef ? ` (related issue #${issueRef})` : ''} at ${ROOT}`)

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} (github.com/LemelyIG/Lemely). Python venv: source ${ROOT}/.venv/bin/activate. Absolute paths only — your cwd resets between bash calls. If ${ROOT}/.venv does not exist, bootstrap it: cd ${ROOT} && python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]" — never reuse the main repo's (/home/sico/Lemely) .venv, which editable-installs lemely from /home/sico/Lemely and would silently import the wrong branch.
Explore code with the tokensave MCP tools (tokensave_context, tokensave_search, tokensave_callers, tokensave_impact) — never spawn an Explore agent for code research.

THE FAILURE UNDER TRIAGE: ${gate ? `gate/check '${gate}'.` : 'unnamed gate — identify it from the log.'} ${logPath ? `The captured failing output is at ${logPath} — read it first; it is the primary evidence.` : 'No log was supplied; the reproduction IS the primary evidence.'} ${issueRef ? `Possibly related to issue #${issueRef}: gh issue view ${issueRef} --repo LemelyIG/Lemely --json number,title,state,body.` : ''}

THE GATES THAT EXIST (know which one you are looking at):
- CI (.github/workflows/ci.yml, runs on every PR and on push to main): test job on py 3.12/3.13/3.14 (ruff check, ruff format --check, mypy lemely, lint-imports, alembic upgrade head, pytest), pre-commit job (pre-commit run --all-files), web job (npm ci, typecheck, oxlint, build).
- Programme gates from the accuracy spec (git -C ${ROOT} show origin/main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md, sections 4, 5, 7): the review-rate ratchet (M0.9: CI fails when review_rate > min(10%, last_merged_review_rate); limbs review_rate_signal <= 8%, review_rate_total <= 10%, per-paper p95 <= 15%), the accuracy-target exit codes of 'lemely measure-accuracy' (lemely/app/cli.py:984, targets in settings.accuracy_eval), the fidelity gate (M1.4), the coherence gate (M1.5), the M0.7a test-split-touch CI assertion, and the golden/architecture tests under tests/.

TRIAGE DISCIPLINE (non-negotiable):
- You DIAGNOSE; you do not fix. Never commit, never push, never close or reopen issues, never edit production code or gate definitions in ${ROOT}. Scratch experiments happen in /tmp or in a throwaway detached worktree OUTSIDE the repo: git -C ${ROOT} worktree add --detach /tmp/gate-triage-<yourlabel> <ref>, with its own venv if it must run tests (python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]") because ${ROOT}'s (and the main repo's, /home/sico/Lemely) .venv editable-installs lemely and would import the wrong code from that checkout. ALWAYS remove your worktree afterwards: git -C ${ROOT} worktree remove --force /tmp/gate-triage-<yourlabel>.
- Never weaken a gate to get green: no loosened thresholds, no deleted assertions, no skip/xfail, no widened tolerances, no narrowed denominators. Whether a gate SHOULD change is the concluder's question to answer, and even then it is a recommendation for a human-reviewed diff, not an action.
- H-numbered issues (#34 #48 #49 #50 #51 #52) are human-only. If the root cause turns out to be "waiting on a human task", the correct conclusion is BLOCKED-ON-HUMAN, not a workaround.
- GEMINI_API_KEY: check presence with test -n only, never print it. Gate reproduction must not spend Gemini tokens unless the gate itself is a measurement gate and there is no cheaper reproduction — and then say so explicitly in your output.
- tests/fixtures/real-papers/*.pdf contains a minor's real handwritten exam scripts — never copy them out of the repo or attach them to anything.
`

// ---------------------------------------------------------------- schemas
const REPRO_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    reproduced: { type: 'boolean' },
    command: { type: 'string', description: 'The exact command (with cwd and venv activation) that reproduces the failure — or that FAILED to reproduce it' },
    exit_code: { type: 'integer', description: '-1 if the command could not be run at all' },
    failure_excerpt: { type: 'string', description: 'The literal failing output, verbatim: the assertion, the traceback tail, the lint message. At most ~80 lines; if you truncate, keep the first failure and the final summary and say [TRUNCATED n lines] where you cut' },
    first_failure: { type: 'string', description: 'One line: the first thing that goes wrong (test id + assertion, file:line for lint/type errors, the breached limb for a ratchet)' },
    environment_notes: { type: 'array', items: { type: 'string' }, description: 'Python version used, branch and sha (git rev-parse HEAD), dirty-tree state (git status --porcelain count), anything differing from CI’s matrix' },
    cannot_reproduce_detail: { type: 'string', description: 'Empty when reproduced. Otherwise: exactly what you ran, what happened instead, and your best explanation of the divergence (version skew, missing env, stale cache, flake, CI-only state)' },
  },
  required: ['reproduced', 'command', 'exit_code', 'failure_excerpt', 'first_failure', 'environment_notes', 'cannot_reproduce_detail'],
}

const HYP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    angle: { type: 'string', enum: ['change-under-test', 'gate-definition', 'environment-fixtures'] },
    hypothesis: { type: 'string', description: 'One falsifiable sentence naming a specific cause' },
    mechanism: { type: 'string', description: 'The causal chain from that cause to the literal failure output, citing file:line where possible' },
    evidence_for: { type: 'array', items: { type: 'string' }, description: 'What you found (diff hunks, blame, config, versions) that makes this plausible' },
    falsifying_experiment: {
      type: 'object',
      additionalProperties: false,
      properties: {
        steps: { type: 'array', items: { type: 'string' }, description: 'Exact commands, runnable as-is (worktree/venv setup included where needed)' },
        prediction_if_true: { type: 'string', description: 'What the experiment shows if the hypothesis is RIGHT' },
        prediction_if_false: { type: 'string', description: 'What it shows if the hypothesis is WRONG — this must genuinely differ from prediction_if_true or the experiment tests nothing' },
        cost_note: { type: 'string', description: 'Runtime and any token spend; experiments must be cheap and must not spend Gemini tokens unless unavoidable' },
      },
      required: ['steps', 'prediction_if_true', 'prediction_if_false', 'cost_note'],
    },
    prior_confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['angle', 'hypothesis', 'mechanism', 'evidence_for', 'falsifying_experiment', 'prior_confidence'],
}

const TEST_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    angle: { type: 'string', enum: ['change-under-test', 'gate-definition', 'environment-fixtures'] },
    hypothesis: { type: 'string', description: 'Restated verbatim from the hypothesiser' },
    ran: { type: 'boolean', description: 'false if the experiment could not be executed — then observed must say why' },
    steps_executed: { type: 'array', items: { type: 'string' }, description: 'What was actually run (deviations from the plan noted)' },
    observed: { type: 'string', description: 'Literal output that matters, verbatim; say [TRUNCATED] where you cut' },
    verdict: { type: 'string', enum: ['supported', 'refuted', 'inconclusive'], description: 'Judged strictly against prediction_if_true vs prediction_if_false' },
    verdict_reason: { type: 'string' },
    cleanup_done: { type: 'boolean', description: 'true only if every scratch worktree/venv you created was removed' },
  },
  required: ['angle', 'hypothesis', 'ran', 'steps_executed', 'observed', 'verdict', 'verdict_reason', 'cleanup_done'],
}

const CONCLUDE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    root_cause: { type: 'string', description: 'The named cause, with the evidence chain that survives the experiments. If nothing survived: the honest state of knowledge and the single best next experiment' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    fix_target: { type: 'string', enum: ['code', 'gate', 'both', 'environment', 'blocked-on-human', 'unknown'], description: 'THE question this workflow exists to answer: is the correct fix to change the CODE under test, or to change the GATE itself? environment = CI/env/fixture plumbing, neither code nor gate. blocked-on-human = the cause is an open H-issue or human decision' },
    gate_change_assessment: { type: 'string', enum: ['legitimate', 'moving-the-goalposts', 'not-applicable'], description: 'REQUIRED whenever fix_target is gate or both: a gate change is legitimate only when the gate mismeasures its own stated intent (wrong denominator, wrong fixture, wrong version pin). It is moving the goalposts when the gate correctly reports a real regression and the change would loosen a threshold, delete an assertion, skip a test, widen a tolerance, or narrow a denominator to get green. not-applicable otherwise' },
    gate_change_justification: { type: 'string', description: 'When gate/both: why this is or is not goalpost-moving, in terms of the gate’s stated intent (cite the spec section or test docstring). Empty string when not-applicable' },
    fix: { type: 'string', description: 'The concrete recommended fix: file(s), what changes, and the regression test that should pin it. A recommendation — this workflow implements nothing' },
    ratchet_note: { type: 'string', description: 'If the gate is the review-rate ratchet or another programme gate: what the correct non-goalpost-moving path is (e.g. reduce trigger volume, not raise the limit). Empty string otherwise' },
    remaining_unknowns: { type: 'array', items: { type: 'string' } },
    next_command: { type: 'string', description: 'The single command a human or orchestrator should run next (to verify the fix hypothesis or gather the missing evidence)' },
  },
  required: ['root_cause', 'confidence', 'fix_target', 'gate_change_assessment', 'gate_change_justification', 'fix', 'ratchet_note', 'remaining_unknowns', 'next_command'],
}

// ---------------------------------------------------------------- Phase 1: Reproduce
phase('Reproduce')
log('accuracy-gate-triage: reproducing the failure locally')

const repro = await agent(`${GROUND}
You are the REPRODUCER. Get the failure to happen locally and capture it literally.
1. ${logPath ? `Read ${logPath} in full first and extract the failing command and the first failure from it.` : `Work out the failing command from the gate name '${gate}' and the gate list in GROUND.`}
2. Run the same check locally (venv activated; note your Python version vs CI's 3.12/3.13/3.14 matrix). For a programme gate, run its actual entry point (the ratchet check, 'lemely measure-accuracy' if that is the gate and it can run without new Gemini spend — if it cannot, reproduce the gate's DECISION step over the last saved records instead and say so).
3. Capture the literal output: exact assertion, traceback tail, lint/type error lines, or breached ratchet limb. Do not paraphrase.
4. If it does NOT reproduce, that is the finding, not a defeat: fill cannot_reproduce_detail with what you ran, what happened, and the most likely divergence (version skew, missing env var, stale cache/fixtures, flaky test, CI-only state). Try at most one variation (e.g. the CI Python version via a fresh /tmp venv) before settling on non-reproduction.
Do not fix anything. Do not modify the tree.`,
  { label: 'reproduce', phase: 'Reproduce', model: 'sonnet', schema: REPRO_SCHEMA })

if (!repro) {
  log('accuracy-gate-triage: reproducer returned null — cannot triage what cannot even be attempted. Reporting that as the outcome.')
  return {
    ok: false,
    error: 'reproduce-agent-failed',
    gate,
    log_path: logPath,
    detail: 'The reproduction agent itself failed before producing evidence. Re-run the workflow; if it fails again, run the gate by hand and pass its output via log_path.',
  }
}
log(`accuracy-gate-triage: reproduced=${repro.reproduced} — ${repro.first_failure || repro.cannot_reproduce_detail}`)

// ---------------------------------------------------------------- Phase 2: Hypothesise
phase('Hypothesise')
log('accuracy-gate-triage: three rival hypotheses, one per angle')

const HYP_COMMON = `${GROUND}
REPRODUCTION EVIDENCE (from the reproducer — treat the literal excerpt as ground truth): ${JSON.stringify(repro)}
You are ONE of three rival hypothesisers, each locked to a different angle. Propose the single best root-cause hypothesis FROM YOUR ANGLE ONLY, even if you privately suspect another angle is right — the rivalry is the method; the concluder arbitrates. Your falsifying experiment must be cheap, concrete, and genuinely able to come out either way. If the failure did not reproduce locally, hypothesise about the DIVERGENCE (why CI fails and local passes) from your angle.`

const hypothesesRaw = await parallel([
  () => agent(`${HYP_COMMON}
YOUR ANGLE: the CHANGE UNDER TEST. The recent diff broke something real. Look at what changed: git -C ${ROOT} log --oneline -15, git -C ${ROOT} diff origin/develop...HEAD --stat (fall back to HEAD~5..HEAD if develop is not a useful base), git blame on the failing file/assertion. Find the specific hunk whose behaviour the gate is correctly rejecting. angle='change-under-test'.`,
    { label: 'hyp-change', phase: 'Hypothesise', model: 'sonnet', schema: HYP_SCHEMA }),
  () => agent(`${HYP_COMMON}
YOUR ANGLE: the GATE'S OWN DEFINITION. The gate itself mismeasures: wrong denominator, stale threshold or baseline value, a ratchet reading the wrong last-merged figure, an assertion testing an implementation detail rather than the stated intent, a version-pinned linter drifting from the code, a test asserting on unstable ordering. Read the gate's source (the failing test, the CI step, the ratchet computation) and its stated intent (docstring, spec section 5/M0.9 for the review-rate ratchet) and find the mismatch. angle='gate-definition'.`,
    { label: 'hyp-gate', phase: 'Hypothesise', model: 'sonnet', schema: HYP_SCHEMA }),
  () => agent(`${HYP_COMMON}
YOUR ANGLE: the ENVIRONMENT AND FIXTURES. Nothing about the logic changed — the substrate did: Python version skew across the 3.12/3.13/3.14 matrix, dependency drift (uv.lock vs installed), a stale or regenerated fixture corpus (the M0.0 fixture repair regenerates golden fixtures — a baseline captured pre-repair mismatches post-repair fixtures), cache state, a missing env var in CI, dirty-tree residue, tool version differences (ruff/mypy/pre-commit pins). angle='environment-fixtures'.`,
    { label: 'hyp-env', phase: 'Hypothesise', model: 'sonnet', schema: HYP_SCHEMA }),
])
const hypotheses = hypothesesRaw.filter(h => h !== null && h !== undefined)
if (hypotheses.length < hypothesesRaw.length) {
  log(`accuracy-gate-triage: ${hypothesesRaw.length - hypotheses.length} hypothesiser(s) returned null — that angle goes untested and the concluder will be told.`)
}
if (hypotheses.length === 0) {
  log('accuracy-gate-triage: no hypotheses produced — returning the reproduction evidence alone.')
  return {
    ok: false,
    error: 'no-hypotheses',
    gate,
    reproduction: repro,
    detail: 'All three hypothesisers failed. The reproduction evidence is preserved above; re-run the workflow or triage by hand from it.',
  }
}
log(`accuracy-gate-triage: ${hypotheses.length} hypothesis(es): ${hypotheses.map(h => `[${h.angle}] ${h.hypothesis}`).join(' || ')}`)

// ---------------------------------------------------------------- Phase 3: Test
phase('Test')
log(`accuracy-gate-triage: running ${hypotheses.length} falsifying experiment(s)`)

const experiments = await pipeline(
  hypotheses,
  async (hyp) => {
    if (!hyp) return null
    return agent(`${GROUND}
REPRODUCTION EVIDENCE: ${JSON.stringify(repro)}
You are the EXPERIMENTER for one hypothesis. Run its falsifying experiment exactly as specified and judge the outcome strictly against the two predictions — not against what feels right.
THE HYPOTHESIS: ${JSON.stringify(hyp)}
Rules: follow falsifying_experiment.steps; note any forced deviation in steps_executed. Scratch work in /tmp or a throwaway worktree per GROUND, removed afterwards (cleanup_done). If a step cannot run (missing tool, would spend Gemini tokens, needs a human), set ran=false and verdict='inconclusive' with the reason in observed. 'supported' requires the observation to match prediction_if_true AND not match prediction_if_false; ambiguity is 'inconclusive', not a coin flip.`,
      { label: `test-${hyp.angle}`, phase: 'Test', model: 'sonnet', schema: TEST_SCHEMA })
  },
)
const testedCount = experiments.filter(e => e !== null && e !== undefined).length
if (testedCount < hypotheses.length) {
  log(`accuracy-gate-triage: ${hypotheses.length - testedCount} experiment agent(s) returned null — those hypotheses remain untested.`)
}

// ---------------------------------------------------------------- Phase 4: Conclude
phase('Conclude')
log('accuracy-gate-triage: concluding — opus names the cause and answers code-vs-gate')

const conclusion = await agent(`${GROUND}
You are the CONCLUDER. Arbitrate between the rival hypotheses using only the evidence below, name the root cause, and answer the question this workflow exists for: is the correct fix to change the CODE, or to change the GATE — and if the gate, is that legitimate or moving the goalposts?

REPRODUCTION: ${JSON.stringify(repro)}
HYPOTHESES (${hypotheses.length} of 3 angles produced one): ${JSON.stringify(hypotheses)}
EXPERIMENTS (null = the experiment agent failed; an untested hypothesis is neither supported nor refuted): ${JSON.stringify(experiments)}

Rules of judgment:
- Weigh experiment verdicts over prior plausibility. Two 'supported' verdicts pointing at different causes means you re-examine mechanisms for compatibility (both can be links in one chain) before picking; say which observation discriminates.
- fix_target='gate' with gate_change_assessment='legitimate' requires you to show the gate violates ITS OWN stated intent (cite the docstring, CI step, or spec section — for the review-rate ratchet that is spec section 5/M0.9: signal <= 8%, total <= 10%, p95 <= 15%, ratchet min(10%, last_merged)). A gate correctly reporting a real regression that someone finds inconvenient is 'moving-the-goalposts' — say so bluntly, and put the legitimate alternative (fix the code) in fix.
- Never recommend skip/xfail, threshold loosening, assertion deletion, tolerance widening, or denominator narrowing as a "fix". If the honest recommendation is "revert the change under test", say that.
- If the surviving cause is an unmet human task (H-issues #34 #48 #49 #50 #51 #52 or an unapproved decision), fix_target='blocked-on-human' and next_command is how to surface it (e.g. write it to BUILD/BLOCKERS.md), never a workaround.
- If nothing survived, confidence='low', fix_target='unknown', and next_command is the single most informative next experiment.
This workflow implements nothing: your fix is a recommendation for a diff a human or another workflow will produce and review.`,
  { label: 'conclude', phase: 'Conclude', schema: CONCLUDE_SCHEMA })

if (!conclusion) {
  log('accuracy-gate-triage: concluder returned null — returning the raw evidence so the triage is not lost.')
  return {
    ok: false,
    error: 'conclude-failed',
    gate,
    log_path: logPath,
    issue: issueRef,
    reproduction: repro,
    hypotheses,
    experiments,
  }
}

log(`accuracy-gate-triage: ROOT CAUSE (${conclusion.confidence}): ${conclusion.root_cause} | fix_target=${conclusion.fix_target}${conclusion.fix_target === 'gate' || conclusion.fix_target === 'both' ? ` (${conclusion.gate_change_assessment})` : ''}`)

return {
  ok: true,
  gate,
  log_path: logPath,
  issue: issueRef,
  reproduced: repro.reproduced,
  root_cause: conclusion.root_cause,
  fix_target: conclusion.fix_target,
  gate_change_assessment: conclusion.gate_change_assessment,
  conclusion,
  reproduction: repro,
  hypotheses,
  experiments,
}
