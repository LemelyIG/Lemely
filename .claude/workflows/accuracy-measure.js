export const meta = {
  name: 'accuracy-measure',
  description: 'Run one measurement sweep honestly and decide whether the result is reportable: costed preflight before any spend, cache-aware sweep (aa-floor | ablation | ab | regression), four independent analyses, opus adjudication against the A/A floor and n-floors. "Not reportable, with reason" is a successful outcome of this workflow, not a failure.',
  phases: [
    { title: 'Preflight', detail: 'One sonnet agent costs the run at corrected GA pricing, checks both ceilings, the API key, the repaired corpus and the split BEFORE anything is spent; unsafe means return early' },
    { title: 'Sweep', detail: 'Sonnet accuracy-measurer agents execute the repeats/arms and write raw records under BUILD/accuracy-runs/<run_label>/' },
    { title: 'Analyse', detail: 'Four parallel sonnet analysts: point estimate + exclusion funnel; McNemar + Wilson; churn vs the A/A floor; review-rate impact against the two-part ratchet' },
    { title: 'Adjudicate', detail: 'One opus agent answers the four honesty questions explicitly and returns REPORTABLE or not-reportable-with-reason' },
  ],
}

// ---------------------------------------------------------------- args guard
const MODES = ['aa-floor', 'ablation', 'ab', 'regression']
if (!args || args.mode === undefined || args.mode === null || args.mode === '') {
  log(`accuracy-measure: args.mode is required. Call as workflow('accuracy-measure', { run_label: '<name>', mode: '${MODES.join("' | '")}', baseline_label: '<optional>', cache_bypass: true|false, n: <repeats for aa-floor> }).`)
  return { ok: false, error: 'missing-mode', detail: `args.mode must be one of: ${MODES.join(', ')}` }
}
const mode = String(args.mode)
if (!MODES.includes(mode)) {
  log(`accuracy-measure: unknown mode ${JSON.stringify(args.mode)}. Allowed: ${MODES.join(', ')}.`)
  return { ok: false, error: 'unknown-mode', got: String(args.mode), allowed: MODES }
}

let runLabel = (args.run_label !== undefined && args.run_label !== null && String(args.run_label).length > 0) ? String(args.run_label) : ''
if (runLabel === '') {
  runLabel = `${mode}-unlabelled`
  log(`accuracy-measure: no run_label supplied; defaulting to '${runLabel}'. The sweep agent will append a date suffix if BUILD/accuracy-runs/${runLabel}/ already exists, so results are not silently overwritten. Prefer passing an explicit run_label.`)
}

const baselineLabel = (args.baseline_label !== undefined && args.baseline_label !== null) ? String(args.baseline_label) : ''

let n = 1
if (mode === 'aa-floor') {
  n = (args.n !== undefined && args.n !== null) ? Number(args.n) : 5
  if (!Number.isInteger(n) || n < 2) {
    log(`accuracy-measure: aa-floor needs an integer n >= 2 repeats; got ${JSON.stringify(args.n)}. Defaulting to n=5.`)
    n = 5
  }
  if (n > 10) {
    log(`accuracy-measure: capping aa-floor repeats from ${n} to 10 to bound spend. Pass smaller n explicitly if 10 is still too many.`)
    n = 10
  }
}

let cacheBypass = Boolean(args.cache_bypass)
if (mode === 'aa-floor' && !cacheBypass) {
  log('accuracy-measure: aa-floor is meaningless against the cache (identical fingerprints return identical answers — a false zero churn). Forcing cache_bypass=true.')
  cacheBypass = true
}
if ((mode === 'ab' || mode === 'regression') && !cacheBypass) {
  log('accuracy-measure: WARNING — cache_bypass=false on an A/B-shaped run. If both arms share a params fingerprint the cache returns a false zero delta. The adjudicator will be told.')
}

const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'
log(`accuracy-measure: mode=${mode} run_label=${runLabel} cache_bypass=${cacheBypass}${mode === 'aa-floor' ? ` n=${n}` : ''}${baselineLabel ? ` baseline_label=${baselineLabel}` : ''} root=${ROOT}`)

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} (github.com/LemelyIG/Lemely). Python venv: source ${ROOT}/.venv/bin/activate. Absolute paths only — your cwd resets between bash calls. If ${ROOT}/.venv does not exist, bootstrap it: cd ${ROOT} && python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]" — never reuse the main repo's (/home/sico/Lemely) .venv, which editable-installs lemely from /home/sico/Lemely and would silently import the wrong branch.
THE SPEC lives on main: git -C ${ROOT} show origin/main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md (sections: 3 record model, 4 milestones, 5 review budget, 7 sequencing, 8 cost, 10 failure modes).
Explore code with the tokensave MCP tools (tokensave_context, tokensave_search, tokensave_callers) — never spawn an Explore agent for code research.

THIS RUN: mode=${mode}, run_label=${runLabel}, cache_bypass=${cacheBypass}${mode === 'aa-floor' ? `, n=${n} repeats` : ''}${baselineLabel ? `, baseline_label=${baselineLabel}` : ''}.
WORKSPACE for this run: ${ROOT}/BUILD/accuracy-runs/${runLabel}/ — manifest.json plus one records file per arm/repeat. BUILD/accuracy-runs/ may not exist yet; mkdir -p it. Do not write anywhere else, and NEVER git-add or commit anything from this workflow.

MEASUREMENT SUBSTRATE (verified against the working tree):
- The harness is lemely/accuracy/harness.py (load_golden_cases, measure_accuracy, save_result); the CLI entry is 'lemely measure-accuracy' at lemely/app/cli.py:984, golden corpus at tests/golden/ (one directory per case).
- lemely/eval/ (EvalRecord, RunManifest, the six pure analyses) is M0.1/#25 and may or may not have landed yet — check before assuming. If it exists, emit and analyse EvalRecords; if not, work from the harness's saved result JSON and SAY SO in your output — do not fake record-level data.
- lemely.toml: model=gemini-2.5-flash (line 16), per_run_token_ceiling=2000000 (line 19), total_usd_ceiling=25.00 (line 20). Both ceilings are PRE-FLIGHT checks in the code, not hard stops: one request can overshoot.
- Corrected GA pricing for gemini-2.5-flash: $0.30 per 1M input tokens, $2.50 per 1M output tokens (thinking tokens count as output). Until M0.2/#26 lands, the in-repo ledger understates real spend 2-4x and never counted thoughts_token_count — always re-cost from raw token counts at the corrected rates; if only ledgered USD is available, multiply it by 4 as the pessimistic bound.
- GEMINI_API_KEY lives in the environment only — never in lemely.toml, never committed, never echoed into any output.

STATISTICAL HONESTY RULES (spec sections 5 and 10 — violating any of these makes the result NOT REPORTABLE):
- Every interval, power calculation and paired test collapses to DISTINCT LEAF QUESTIONS first, never raw records. The current corpus is 28 distinct leaves, not 68 records.
- Abstention is an OUTCOME counted in the denominator, not an error and not an exclusion. An extractor returning fewer, easier questions must not be able to score higher (D18).
- Any A/B delta below the published A/A churn floor is noise. If no A/A floor has been published yet (M0.3/#27 still open), NO A/B claim is reportable.
- A metric below its n-floor is reported as UNDERPOWERED, not as a number with a conclusion attached.
- The det parse path is the majority path; a result measured only on the gemini path can move every number while the product stands still — always report per-parse-path where the records allow it.
- Review budget ratchet: review_rate_signal <= 8%, review_rate_total <= 10%, per-paper p95 <= 15%; CI fails when review_rate > min(10%, last_merged_review_rate); baseline being ratcheted down from 19.1%.

SEQUENCING PRECONDITIONS relevant to measurement (spec section 7): M0.0/#56 fixture repair -> any baseline run; M0.8/#32 fixtures final -> M0.3 A/A floor and M0.4 ablation; M0.2/#26 cache-bypass seam -> A/A floor; M0.2 pricing + token-ceiling fix -> any multi-sweep run; M0.3/#27 A/A floor -> any A/B claim. Check issue state with: gh issue view <n> --repo LemelyIG/Lemely --json number,state,title.
SPLIT DISCIPLINE: never read the test split. The split field and test-touch ledger are M0.7a/#31; if that has not landed, the golden corpus counts as dev and the run manifest must record split='dev (pre-M0.7a)'. Reading the test split without an authorisation token is a blocking defect, not a judgement call.
STANDING RULES: never commit, never push, never close or reopen GitHub issues; H-numbered issues (#34 #48 #49 #50 #51 #52) are human-only. tests/fixtures/real-papers/*.pdf contains a minor's real handwritten exam scripts — never redistribute or attach them to anything outward-facing.
`

// ---------------------------------------------------------------- schemas
const PREFLIGHT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    safe_to_run: { type: 'boolean', description: 'true only if every check below passed AND estimated_usd fits inside the remaining headroom' },
    estimated_usd: { type: 'number', description: 'Estimated total cost of this run at corrected GA pricing ($0.30/1M in, $2.50/1M out, thinking counted as output), across all arms/repeats' },
    estimated_tokens_in: { type: 'number' },
    estimated_tokens_out: { type: 'number', description: 'Includes an allowance for thinking tokens' },
    headroom_usd: { type: 'number', description: 'total_usd_ceiling (25.00) minus past spend re-costed at corrected rates (or ledgered USD x4 if raw token counts are unavailable)' },
    token_ceiling_ok: { type: 'boolean', description: 'true if the per-arm/per-repeat estimate fits under per_run_token_ceiling=2000000' },
    api_key_present: { type: 'boolean', description: 'GEMINI_API_KEY set in the environment (check existence only; never print it). Cross-check with: lemely doctor' },
    corpus_repaired: { type: 'boolean', description: 'M0.0/#56 closed AND the fixture renderer round-trip assertion exists — the corpus is the repaired one, not the corrupt pre-M0.0 one' },
    preconditions_met: { type: 'boolean', description: 'Every spec-section-7 precondition for THIS mode has landed (see GROUND). aa-floor additionally requires the M0.2 cache-bypass seam to exist in code' },
    split_respected: { type: 'boolean', description: 'The planned run reads train/dev only; test split untouched' },
    blocking_reasons: { type: 'array', items: { type: 'string' }, description: 'Every reason safe_to_run is false, each concrete enough to act on. Empty if safe' },
    notes: { type: 'array', items: { type: 'string' }, description: 'Non-blocking caveats the adjudicator must see (e.g. "no A/A floor published yet — result cannot support an A/B claim")' },
  },
  required: ['safe_to_run', 'estimated_usd', 'estimated_tokens_in', 'estimated_tokens_out', 'headroom_usd', 'token_ceiling_ok', 'api_key_present', 'corpus_repaired', 'preconditions_met', 'split_respected', 'blocking_reasons', 'notes'],
}

const SWEEP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    completed: { type: 'boolean', description: 'true only if every planned call finished and every records file was written' },
    arm: { type: 'string', description: 'Which arm/repeat-set this agent ran, e.g. "extract+mark", "oracle+mark", "baseline", "candidate", "aa-repeats"' },
    run_ids: { type: 'array', items: { type: 'string' }, description: 'One run_id per repeat/arm executed, derived from a bash date stamp (date +%Y%m%dT%H%M%S), never invented' },
    records_paths: { type: 'array', items: { type: 'string' }, description: 'Absolute paths of the records/result files written under BUILD/accuracy-runs/' },
    record_format: { type: 'string', enum: ['eval-records-jsonl', 'harness-result-json'], description: 'eval-records-jsonl only if lemely/eval (M0.1) has landed and was used' },
    n_records: { type: 'integer' },
    distinct_leaves: { type: 'integer', description: 'Distinct leaf questions covered — the unit every statistic collapses to' },
    cache_mode: { type: 'string', description: 'What the cache actually did: "bypassed", "read-write", or "no-seam-exists (pre-M0.2)"' },
    actual_cost_usd: { type: 'number', description: 'Re-costed from raw usage token counts at $0.30/1M in + $2.50/1M out (thinking as output). NOT the ledger figure' },
    tokens_in: { type: 'number' },
    tokens_out: { type: 'number', description: 'Including thoughts_token_count where the API reports it' },
    anomalies: { type: 'array', items: { type: 'string' }, description: 'Anything that could poison the analysis: retries, truncated responses, ceiling near-misses, fixtures that failed to load, cache hits during a bypassed run' },
  },
  required: ['completed', 'arm', 'run_ids', 'records_paths', 'record_format', 'n_records', 'distinct_leaves', 'cache_mode', 'actual_cost_usd', 'tokens_in', 'tokens_out', 'anomalies'],
}

const ESTIMATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    point_estimates: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          name: { type: 'string' },
          value: { type: 'number' },
          numerator: { type: 'integer' },
          denominator: { type: 'integer' },
          denominator_population: { type: 'string', description: 'Exactly which rows the denominator counts, e.g. "all 28 distinct leaves incl. abstain/unmatched"' },
          per_parse_path: { type: 'string', description: 'det vs gemini breakdown, or "not separable from these records" with why' },
        },
        required: ['name', 'value', 'numerator', 'denominator', 'denominator_population', 'per_parse_path'],
      },
    },
    exclusion_funnel: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          stage: { type: 'string' },
          count: { type: 'integer' },
          reason: { type: 'string' },
        },
        required: ['stage', 'count', 'reason'],
      },
      description: 'Every row that fell out between "all questions in corpus" and the final denominator, and why. An empty funnel means nothing was excluded — state that explicitly in caveats',
    },
    abstentions_counted_as_outcome: { type: 'boolean', description: 'true only if abstain rows sit inside the denominator, not excluded' },
    distinct_leaves: { type: 'integer' },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['point_estimates', 'exclusion_funnel', 'abstentions_counted_as_outcome', 'distinct_leaves', 'caveats'],
}

const PAIRED_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    applicable: { type: 'boolean', description: 'false for a single-arm run (aa-floor) — then fill numeric fields with -1 and say so in caveats' },
    n_distinct_leaves: { type: 'integer' },
    discordant_b: { type: 'integer', description: 'Leaves arm A got right and arm B got wrong (-1 if not applicable)' },
    discordant_c: { type: 'integer', description: 'Leaves arm A got wrong and arm B got right (-1 if not applicable)' },
    mcnemar_p_value: { type: 'number', description: 'Exact binomial McNemar on the discordant pairs, computed on distinct leaves (-1 if not applicable)' },
    wilson_intervals: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          name: { type: 'string' },
          estimate: { type: 'number' },
          low: { type: 'number' },
          high: { type: 'number' },
          n: { type: 'integer' },
        },
        required: ['name', 'estimate', 'low', 'high', 'n'],
      },
    },
    n_floor_met: { type: 'boolean', description: 'Is n large enough to power the claimed effect size? If not, the result is UNDERPOWERED — say what n would be needed' },
    same_denominator_both_arms: { type: 'boolean', description: 'Both arms cover the identical leaf population (-1 semantics do not apply: use false and explain in caveats for single-arm runs)' },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['applicable', 'n_distinct_leaves', 'discordant_b', 'discordant_c', 'mcnemar_p_value', 'wilson_intervals', 'n_floor_met', 'same_denominator_both_arms', 'caveats'],
}

const CHURN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    per_repeat_disagreement: { type: 'array', items: { type: 'number' }, description: 'Pairwise per-question disagreement rates across repeats (empty unless this run has repeats)' },
    observed_churn: { type: 'number', description: 'This run’s churn figure, or for A/B-shaped runs the observed |delta| to compare against the floor (-1 if not computable)' },
    published_floor_exists: { type: 'boolean', description: 'Has an A/A churn floor been published (M0.3/#27 closed, figure recorded in the report and BUILD/DECISIONS.md)?' },
    published_floor_value: { type: 'number', description: 'The published floor with its n, or -1 if none exists' },
    published_floor_n: { type: 'integer', description: 'The n behind the published floor, or -1' },
    delta_vs_floor: { type: 'string', description: 'One sentence: is the observed effect above or below the floor, or "no floor exists so no A/B delta can be judged"' },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['per_repeat_disagreement', 'observed_churn', 'published_floor_exists', 'published_floor_value', 'published_floor_n', 'delta_vs_floor', 'caveats'],
}

const RATCHET_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    review_rate_signal: { type: 'number', description: 'Fraction of question-level rows with non-empty triggers, excluding the random audit (-1 if not computable from these records)' },
    review_rate_total: { type: 'number', description: 'Same but including the random audit; equal to signal until M4/T1.10 exists (-1 if not computable)' },
    per_paper_p95: { type: 'number', description: '-1 if not computable' },
    last_merged_review_rate: { type: 'number', description: 'The ratchet’s current value (starting point 19.1% = 0.191), or -1 if not yet recorded anywhere' },
    ratchet_pass: { type: 'boolean', description: 'review_rate <= min(0.10, last_merged_review_rate)? Use the recorded starting value 0.191 if nothing newer is recorded' },
    breach_detail: { type: 'string', description: 'Which limb breached and by how much, or "no breach", or "not computable: <why>"' },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['review_rate_signal', 'review_rate_total', 'per_paper_p95', 'last_merged_review_rate', 'ratchet_pass', 'breach_detail', 'caveats'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    reportable: { type: 'boolean' },
    delta_above_aa_floor: { type: 'string', enum: ['yes', 'no', 'no-floor-published', 'not-applicable'], description: 'not-applicable only for runs that make no A/B-shaped claim (aa-floor itself, a pure baseline)' },
    n_above_floor: { type: 'string', enum: ['yes', 'no', 'unknown'], description: 'Is n (distinct leaves) above the floor for the claimed effect?' },
    same_denominator_both_arms: { type: 'string', enum: ['yes', 'no', 'single-arm', 'unknown'] },
    abstentions_counted_as_outcome: { type: 'string', enum: ['yes', 'no', 'unknown'] },
    headline: { type: 'string', description: 'One sentence. If reportable: the finding with its interval and n. If not: "NOT REPORTABLE: <reason>"' },
    not_reportable_reason: { type: 'string', description: 'Empty string when reportable; otherwise the specific failed check and what would make a future run reportable' },
    evidence: { type: 'array', items: { type: 'string' }, description: 'The concrete numbers and file paths (records under BUILD/accuracy-runs/) that back the headline' },
    follow_ups: { type: 'array', items: { type: 'string' }, description: 'What to run or land next, with issue numbers where relevant' },
  },
  required: ['reportable', 'delta_above_aa_floor', 'n_above_floor', 'same_denominator_both_arms', 'abstentions_counted_as_outcome', 'headline', 'not_reportable_reason', 'evidence', 'follow_ups'],
}

// ---------------------------------------------------------------- Phase 1: Preflight
phase('Preflight')
log(`accuracy-measure: preflight — costing the ${mode} run before anything is spent`)

const preflight = await agent(`${GROUND}
You are the PREFLIGHT check. NOTHING may be spent in this phase: no Gemini calls, no harness runs. Read-only inspection and arithmetic only.

Do all of the following and fill the schema honestly:
1. COST THE RUN. Corpus today: run 'ls ${ROOT}/tests/golden' and count case directories; measure their input sizes. Estimate tokens per correction call (input: scheme + answers + prompt overhead; output: structured marks + a thinking allowance), then multiply by the number of calls this mode implies: ${mode === 'aa-floor' ? `n=${n} full-corpus repeats` : mode === 'ablation' ? 'two arms (extract+mark and oracle+mark) over the full corpus' : 'two arms (baseline and candidate) over the full corpus' + (baselineLabel ? `, minus the baseline arm if saved records for baseline_label='${baselineLabel}' already exist under ${ROOT}/BUILD/accuracy-runs/${baselineLabel}/` : '')}. Price at $0.30/1M in, $2.50/1M out. If 'lemely estimate-cost' exists and runs without an API call, cross-check against it.
2. CEILINGS. Read lemely.toml lines 16-20. Check the per-arm/per-repeat token estimate against per_run_token_ceiling=2000000 and the total estimate against remaining USD headroom under total_usd_ceiling=25.00 (re-cost past spend per GROUND). Remember both ceilings are pre-flight checks in the product code too — one call can overshoot, so leave margin.
3. API KEY. Confirm GEMINI_API_KEY is set (test -n, never print it) and 'lemely doctor' passes.
4. CORPUS. Confirm the corpus is the repaired one: gh issue view 56 --repo LemelyIG/Lemely --json state must be CLOSED, and the fixture renderer's generation-time round-trip assertion must exist in the code (find it with tokensave_search). If #56 is open, the fixtures are the known-corrupt pre-M0.0 corpus and NO baseline-shaped run is valid: block.
5. PRECONDITIONS for mode=${mode} per GROUND's sequencing list — check each named issue's state with gh and, where the precondition is a code seam (the M0.2 cache_mode bypass), verify the seam exists in code, not just that the issue closed.
6. SPLIT. Confirm the planned run touches train/dev only (see SPLIT DISCIPLINE in GROUND).
Set safe_to_run=false with concrete blocking_reasons if ANY of 2-6 fails or the estimate exceeds headroom. Put reportability caveats that do NOT block spending (e.g. "M0.3 floor unpublished, so no A/B claim can come of this") in notes.`,
  { label: 'preflight', phase: 'Preflight', model: 'sonnet', schema: PREFLIGHT_SCHEMA })

if (!preflight) {
  log('accuracy-measure: preflight agent returned null — refusing to spend anything without a costed go-ahead.')
  return { reportable: false, headline: 'NOT RUN: preflight agent failed to return; nothing was spent.', evidence: [], cost_usd: 0, mode, run_label: runLabel }
}
if (!preflight.safe_to_run) {
  log(`accuracy-measure: preflight says NOT SAFE — returning without spending anything. Reasons: ${preflight.blocking_reasons.join(' | ')}`)
  return {
    reportable: false,
    headline: `NOT RUN: preflight blocked the ${mode} sweep before any spend. ${preflight.blocking_reasons[0] || ''}`,
    evidence: preflight.blocking_reasons,
    cost_usd: 0,
    mode,
    run_label: runLabel,
    preflight,
  }
}
log(`accuracy-measure: preflight PASSED — estimated $${preflight.estimated_usd} against $${preflight.headroom_usd} headroom. Notes: ${preflight.notes.join(' | ') || 'none'}`)

// ---------------------------------------------------------------- Phase 2: Sweep
phase('Sweep')

const SWEEP_COMMON = `${GROUND}
PREFLIGHT RESULT (already passed — do not re-litigate, but respect its notes): ${JSON.stringify(preflight)}
You EXECUTE the run and report raw evidence. Rules of execution:
- mkdir -p ${ROOT}/BUILD/accuracy-runs/${runLabel}; if it already contains a manifest from a previous run, append -$(date +%Y%m%dT%H%M%S) to the directory name, use that instead, and record the actual path in records_paths.
- Derive run_ids from bash: $(date +%Y%m%dT%H%M%S) plus the arm name. Never invent timestamps.
- Write a manifest.json capturing: git sha (git -C ${ROOT} rev-parse HEAD), model, params (temperature/top_p/seed/thinking budget where settable), cache_mode actually in effect, split ('dev (pre-M0.7a)' if the split field has not landed), corpus listing of tests/golden.
- Record per-call usage token counts (prompt, candidates, thoughts) and re-cost at corrected pricing for actual_cost_usd.
- If any call fails after the product's retries, record it in anomalies and continue the sweep; do not silently drop the case from the denominator.
- Abstentions/unmatched are outcomes to be recorded, never rows to be deleted.
- STOP the sweep and report completed=false if cumulative re-costed spend reaches 150% of the preflight estimate ($${preflight.estimated_usd}) — that means the estimate was wrong and a human should look before more is spent.`

let sweepThunks = []
if (mode === 'aa-floor') {
  sweepThunks = [
    () => agent(`${SWEEP_COMMON}
YOUR ARM: 'aa-repeats'. Run the IDENTICAL configuration ${n} times over the full golden corpus with the cache BYPASSED on every repeat (the M0.2 cache_mode seam — preflight verified it exists). Identical fingerprint everywhere: same model, same prompts, same params; the only thing that may differ between repeats is the model's own nondeterminism. Write one records file per repeat (records-repeat-01.jsonl style). If any repeat shows a cache HIT, that repeat is invalid — record it in anomalies and rerun that repeat once; if it hits again, report completed=false.`,
      { label: 'sweep-aa-repeats', phase: 'Sweep', model: 'sonnet', agentType: 'accuracy-measurer', schema: SWEEP_SCHEMA }),
  ]
} else if (mode === 'ablation') {
  sweepThunks = [
    () => agent(`${SWEEP_COMMON}
YOUR ARM: 'extract+mark'. Run the full pipeline arm (extraction then marking) over ALL fixtures, cache ${cacheBypass ? 'BYPASSED' : 'in read-write mode (record this in cache_mode)'}. Write records-extract-mark.jsonl (or the harness result JSON if lemely/eval has not landed — set record_format accordingly).`,
      { label: 'sweep-extract-mark', phase: 'Sweep', model: 'sonnet', agentType: 'accuracy-measurer', schema: SWEEP_SCHEMA }),
    () => agent(`${SWEEP_COMMON}
YOUR ARM: 'oracle+mark'. Run the oracle-transcription arm (marking fed the fixture's ground-truth transcription instead of the extractor's output) over ALL fixtures, cache ${cacheBypass ? 'BYPASSED' : 'in read-write mode (record this in cache_mode)'}. This arm only exists if the M0.4 machinery has landed — verify with tokensave_search before running; if the oracle arm is not implemented, report completed=false with anomalies naming exactly what is missing (do NOT hand-simulate the arm).`,
      { label: 'sweep-oracle-mark', phase: 'Sweep', model: 'sonnet', agentType: 'accuracy-measurer', schema: SWEEP_SCHEMA }),
  ]
} else {
  // ab | regression: two arms, baseline and candidate
  sweepThunks = [
    () => agent(`${SWEEP_COMMON}
YOUR ARM: 'baseline'. ${baselineLabel
    ? `First look for saved records under ${ROOT}/BUILD/accuracy-runs/${baselineLabel}/ — if a complete records set with a manifest exists, REUSE it (zero spend: set actual_cost_usd=0, cache_mode='reused-saved-records', copy the paths into records_paths) and verify its manifest git sha and params so the comparison is like-for-like. Only if no usable saved records exist, run the baseline configuration afresh and say so in anomalies.`
    : 'No baseline_label was supplied, so run the baseline configuration afresh over the full corpus and note in anomalies that a saved baseline would have been cheaper.'} Cache ${cacheBypass ? 'BYPASSED' : 'read-write (record it)'}.`,
      { label: 'sweep-baseline', phase: 'Sweep', model: 'sonnet', agentType: 'accuracy-measurer', schema: SWEEP_SCHEMA }),
    () => agent(`${SWEEP_COMMON}
YOUR ARM: 'candidate'. Measure the configuration at ${ROOT} EXACTLY as it stands right now (HEAD plus any uncommitted diff) over the full corpus — this tree, not any other checkout — cache ${cacheBypass ? 'BYPASSED' : 'read-write (record it — and note that identical fingerprints against the cache produce a false zero delta)'}. Write records-candidate.jsonl. Record the exact git sha and any uncommitted-diff state (git -C ${ROOT} status --porcelain) in the manifest so the adjudicator knows precisely what was measured.`,
      { label: 'sweep-candidate', phase: 'Sweep', model: 'sonnet', agentType: 'accuracy-measurer', schema: SWEEP_SCHEMA }),
  ]
}

log(`accuracy-measure: sweep — launching ${sweepThunks.length} accuracy-measurer agent(s)`)
const sweepRaw = await parallel(sweepThunks)
const sweeps = sweepRaw.filter(s => s !== null && s !== undefined)
if (sweeps.length < sweepRaw.length) {
  log(`accuracy-measure: ${sweepRaw.length - sweeps.length} sweep agent(s) returned null — their arms are missing from the analysis and the adjudicator will be told.`)
}
if (sweeps.length === 0) {
  log('accuracy-measure: every sweep agent failed. Nothing to analyse.')
  return { reportable: false, headline: 'NOT REPORTABLE: the sweep produced no records (all sweep agents failed).', evidence: [], cost_usd: 0, mode, run_label: runLabel, preflight }
}
const costUsd = sweeps.reduce((acc, s) => acc + (typeof s.actual_cost_usd === 'number' && s.actual_cost_usd > 0 ? s.actual_cost_usd : 0), 0)
const incomplete = sweeps.filter(s => !s.completed).map(s => s.arm)
if (incomplete.length > 0) {
  log(`accuracy-measure: sweep arms reported incomplete: ${incomplete.join(', ')} — proceeding to analysis so the failure is characterised, but the adjudicator must treat the result as suspect.`)
}
log(`accuracy-measure: sweep done — ${sweeps.length} arm(s), re-costed spend $${costUsd.toFixed ? costUsd.toFixed(4) : costUsd}`)

// ---------------------------------------------------------------- Phase 3: Analyse
phase('Analyse')

const ANALYSE_COMMON = `${GROUND}
THE SWEEP RESULTS (raw, from the measurer agents — the records files on disk are the ground truth, these summaries just point you at them): ${JSON.stringify(sweeps)}
Read the records files at the listed records_paths yourself. You are a PURE ANALYST: no Gemini calls, no reruns, no editing of any file outside ${ROOT}/BUILD/accuracy-runs/${runLabel}/ (you may write derived analysis JSON there). If lemely/eval's pure analysis functions exist (M0.1), call them instead of reimplementing; otherwise compute with python/scipy in the venv and say which you did in caveats. Collapse to DISTINCT LEAVES before any statistic. If something is not computable from these records, return the -1 sentinel the schema describes and explain in caveats — never substitute a plausible number.`

log('accuracy-measure: analyse — 4 parallel analysts')
const analysisRaw = await parallel([
  () => agent(`${ANALYSE_COMMON}
YOUR ANALYSIS: point estimates with honest denominators. For each arm compute the headline accuracy metric(s) with numerator, denominator, and an explicit statement of the denominator population. Build the full exclusion funnel from "all questions in corpus" down to the final denominator. Verify abstain/unmatched rows are IN the denominator; if the records exclude them, report abstentions_counted_as_outcome=false — do not quietly re-add them. Break out det vs gemini parse path wherever the records allow.`,
    { label: 'analyse-estimate', phase: 'Analyse', model: 'sonnet', schema: ESTIMATE_SCHEMA }),
  () => agent(`${ANALYSE_COMMON}
YOUR ANALYSIS: paired statistics. Applicable only when two arms cover the same leaves (${mode === 'aa-floor' ? 'NOT this run — it is single-configuration; fill sentinels and explain' : 'this run has two arms'}). Pair BY DISTINCT LEAF, compute the discordant counts, exact McNemar p-value, and Wilson intervals per arm. Then answer n_floor_met: with this many distinct leaves, what is the minimum detectable effect at alpha=0.05, power 0.8 — and is the observed effect inside it? Verify both arms share the identical leaf population; if not, same_denominator_both_arms=false and name the differing leaves in caveats.`,
    { label: 'analyse-paired', phase: 'Analyse', model: 'sonnet', schema: PAIRED_SCHEMA }),
  () => agent(`${ANALYSE_COMMON}
YOUR ANALYSIS: churn and the A/A floor. ${mode === 'aa-floor'
    ? 'This IS an A/A run: compute the per-question disagreement rate across every pair of repeats, report per_repeat_disagreement and observed_churn (the floor candidate) with its n. Also check whether a floor is ALREADY published (BUILD/DECISIONS.md and closed #27) so the adjudicator knows whether this run establishes or updates it.'
    : 'Find the published A/A churn floor: search BUILD/DECISIONS.md and the state of #27 (gh issue view 27 --repo LemelyIG/Lemely --json state). If none is published, published_floor_exists=false and delta_vs_floor must say plainly that no A/B delta can be judged against noise. If one exists, compare this run’s observed delta against it.'}`,
    { label: 'analyse-churn', phase: 'Analyse', model: 'sonnet', schema: CHURN_SCHEMA }),
  () => agent(`${ANALYSE_COMMON}
YOUR ANALYSIS: review-rate impact against the two-part ratchet. From question-level rows (mark_point_id is None), compute review_rate_signal (non-empty triggers, excluding any random audit — none exists until M4/T1.10, so signal=total today), review_rate_total, and per-paper p95. Find last_merged_review_rate (BUILD/DECISIONS.md, M0.9 artefacts; the recorded programme starting value is 0.191). ratchet_pass is review_rate <= min(0.10, last_merged_review_rate). If the records carry no triggers field (pre-M0.1), return the -1 sentinels and say exactly what is missing.`,
    { label: 'analyse-ratchet', phase: 'Analyse', model: 'sonnet', schema: RATCHET_SCHEMA }),
])
const [estimateA, pairedA, churnA, ratchetA] = analysisRaw
const failedAnalyses = ['estimate', 'paired', 'churn', 'ratchet'].filter((name, i) => analysisRaw[i] === null || analysisRaw[i] === undefined)
if (failedAnalyses.length > 0) {
  log(`accuracy-measure: analysis agent(s) failed: ${failedAnalyses.join(', ')} — the adjudicator must treat the missing dimension(s) as unknown, which biases toward NOT REPORTABLE.`)
}

// ---------------------------------------------------------------- Phase 4: Adjudicate
phase('Adjudicate')
log('accuracy-measure: adjudicate — one opus agent decides reportability')

const verdict = await agent(`${GROUND}
You are the ADJUDICATOR. Everything below is evidence gathered by other agents; the records under ${ROOT}/BUILD/accuracy-runs/ are the ground truth if anything conflicts. Your ONLY job: decide whether this ${mode} result is REPORTABLE, and if not, record exactly why. "Not reportable, with reason" is a successful outcome of this workflow — never stretch a weak result into a claim.

AFTER you have decided the verdict, record it in BUILD/ACCURACY-STATE.md via the board tool (from ${ROOT}, never edit the file directly):
- python scripts/accuracy_board.py state set last_run_label '${runLabel}'
- python scripts/accuracy_board.py state set last_run_headline '<the headline you just wrote, single-quoted>'
- spend_usd is CUMULATIVE: read the current value with 'python scripts/accuracy_board.py state get spend_usd' (treat missing/empty as 0), add this run's re-costed spend ($${costUsd}), and set the new total: 'python scripts/accuracy_board.py state set spend_usd <old-value-plus-${costUsd}>'.
- If the ratchet analysis produced a real review_rate_total (not the -1 sentinel), also set it: 'python scripts/accuracy_board.py state set review_rate <value>'.

PREFLIGHT: ${JSON.stringify(preflight)}
SWEEPS (${sweeps.length} arm(s)${incomplete.length > 0 ? `; INCOMPLETE arms: ${incomplete.join(', ')}` : ''}): ${JSON.stringify(sweeps)}
ANALYSIS point-estimate: ${JSON.stringify(estimateA)}
ANALYSIS paired: ${JSON.stringify(pairedA)}
ANALYSIS churn/floor: ${JSON.stringify(churnA)}
ANALYSIS ratchet: ${JSON.stringify(ratchetA)}
${failedAnalyses.length > 0 ? `MISSING ANALYSES (agents failed): ${failedAnalyses.join(', ')} — treat those dimensions as unknown; unknown biases toward NOT REPORTABLE.` : ''}

You MUST answer each schema field explicitly, and reportable can be true ONLY if every one of these holds:
1. delta_above_aa_floor: for any A/B-shaped claim, the delta exceeds a PUBLISHED A/A floor. No published floor (M0.3/#27 open) means 'no-floor-published' and NOT reportable as an A/B claim (an aa-floor run reporting the floor itself, or a pure descriptive baseline, is 'not-applicable').
2. n_above_floor: the distinct-leaf n powers the claimed effect. Underpowered means the honest headline is "underpowered at n=<x>", which may itself be reportable as a finding — but never a directional claim.
3. same_denominator_both_arms: both arms cover the identical leaf population ('single-arm' for aa-floor).
4. abstentions_counted_as_outcome: abstain/unmatched sit in the denominator.
Also weigh: incomplete sweep arms, cache_mode (a read-write cache on identical fingerprints yields a false zero — cache_bypass was ${cacheBypass}), records format (pre-M0.1 harness JSON supports fewer claims), and the ratchet result (a ratchet breach is always worth reporting, whatever else failed).
Write the headline the way it should appear in BUILD/JOURNAL.md: number, interval, n, and what it does NOT show.`,
  { label: 'adjudicate', phase: 'Adjudicate', schema: VERDICT_SCHEMA })

if (!verdict) {
  log('accuracy-measure: adjudicator returned null — without adjudication the result is NOT REPORTABLE by definition.')
  return {
    reportable: false,
    headline: 'NOT REPORTABLE: adjudication failed; raw records preserved under BUILD/accuracy-runs/ for a rerun of the analysis.',
    evidence: sweeps.flatMap(s => s.records_paths),
    cost_usd: costUsd,
    mode,
    run_label: runLabel,
    preflight,
    sweeps,
    analyses: { estimate: estimateA, paired: pairedA, churn: churnA, ratchet: ratchetA },
  }
}

log(`accuracy-measure: verdict — ${verdict.reportable ? 'REPORTABLE' : 'NOT REPORTABLE'}: ${verdict.headline}`)

return {
  reportable: verdict.reportable,
  headline: verdict.headline,
  evidence: verdict.evidence,
  cost_usd: costUsd,
  mode,
  run_label: runLabel,
  verdict,
  preflight,
  sweeps,
  analyses: { estimate: estimateA, paired: pairedA, churn: churnA, ratchet: ratchetA },
}
