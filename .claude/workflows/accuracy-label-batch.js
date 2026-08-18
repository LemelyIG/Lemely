export const meta = {
  name: 'accuracy-label-batch',
  description: 'Prepare and QA one batch of the two-pass blind labelling work that a HUMAN performs. This workflow NEVER produces labels: it selects leaves from train/dev, renders blind input forms, and (in mode=qa) checks the human’s returned labels — schema, hash chain, agreement, H8 judgment questions. Ground truth comes from the human, full stop.',
  phases: [
    { title: 'Select', detail: 'One sonnet accuracy-labeller picks stratified leaves from train/dev only, skipping anything already labelled in this pass, and writes the batch manifest' },
    { title: 'Prepare', detail: 'Pipeline over item chunks: render each leaf into a blind labeller input form (model output hidden), then validate required fields including split' },
    { title: 'QA', detail: 'mode=qa only: three parallel sonnet agents check schema + hash chain, compute pass-1/pass-2 and self-agreement, and extract judgment questions for H8' },
    { title: 'Summarise', detail: 'One opus agent reports coverage against the ~300-leaf target, agreement figures, and the questions for the human — and says plainly if the batch is unusable' },
  ],
}

// ---------------------------------------------------------------- args guard
if (!args || args.batch === undefined || args.batch === null || String(args.batch) === '') {
  log("accuracy-label-batch: args.batch is required. Call as workflow('accuracy-label-batch', { batch: '<id, e.g. b01>', size: <leaves>, pass: 1|2, mode: 'prepare'|'qa' }).")
  return { ok: false, error: 'missing-batch', detail: 'args.batch is required, e.g. { batch: "b01", size: 30, pass: 1 }' }
}
const batch = String(args.batch).replace(/[^a-zA-Z0-9_-]/g, '-')
if (batch !== String(args.batch)) {
  log(`accuracy-label-batch: sanitised batch id '${args.batch}' to '${batch}' (it becomes a directory name).`)
}

const pass = Number(args.pass)
if (pass !== 1 && pass !== 2) {
  log(`accuracy-label-batch: args.pass must be 1 (transcription) or 2 (marking); got ${JSON.stringify(args.pass)}.`)
  return { ok: false, error: 'bad-pass', detail: 'pass must be 1 or 2', got: args.pass === undefined ? null : args.pass }
}

const qaMode = Boolean(args && args.mode === 'qa')

let size = (args.size !== undefined && args.size !== null) ? Number(args.size) : 30
if (!Number.isInteger(size) || size < 1) {
  log(`accuracy-label-batch: bad size ${JSON.stringify(args.size)}; defaulting to 30.`)
  size = 30
}
if (size > 60) {
  log(`accuracy-label-batch: capping batch size from ${size} to 60 — a human labels this batch in one sitting; the ~300-leaf target is reached over multiple batches, not one.`)
  size = 60
}

const ROOT = (args && args.root) ? String(args.root) : '/home/sico/Lemely-worktrees/accuracy'
const batchDir = `${ROOT}/BUILD/labelling/batch-${batch}/pass-${pass}`
log(`accuracy-label-batch: batch=${batch} pass=${pass} size=${size} mode=${qaMode ? 'qa (verify returned labels)' : 'prepare (select + render forms)'} dir=${batchDir} root=${ROOT}`)

// ---------------------------------------------------------------- shared ground
const GROUND = `
REPO ROOT FOR THIS TASK: ${ROOT} (github.com/LemelyIG/Lemely). Python venv: source ${ROOT}/.venv/bin/activate. Absolute paths only — your cwd resets between bash calls. If ${ROOT}/.venv does not exist, bootstrap it: cd ${ROOT} && python -m venv .venv && .venv/bin/pip install -e ".[dev,ui,web,db]" — never reuse the main repo's (/home/sico/Lemely) .venv, which editable-installs lemely from /home/sico/Lemely and would silently import the wrong branch.
THE SPEC lives on main: git -C ${ROOT} show origin/main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md — section 6 is the labelling protocol; read it before doing anything else.
Explore code with the tokensave MCP tools (tokensave_context, tokensave_search) — never spawn an Explore agent for code research.

THE ONE RULE THAT DEFINES THIS WORKFLOW: YOU NEVER PRODUCE, EDIT, GUESS, INFER, DRAFT, OR "HELPFULLY COMPLETE" A LABEL. Ground truth comes from a HUMAN. If a label file is missing, the finding is "missing", never a filled-in value. An agent-written label silently poisons every downstream statistic in the programme.

THE BLIND PROTOCOL (spec section 6):
- Pass 1 (transcription): the labeller sees the SCAN REGION ONLY. No mark scheme, no model transcription, no model marks.
- Pass 2 (marking): the labeller sees the mark scheme PLUS THEIR OWN pass-1 transcription. Never the pipeline's transcription, never the pipeline's awarded marks.
- In both passes ALL MODEL OUTPUT IS HIDDEN. Blindness is structural: the labeller tooling must not import pipeline modules (that no-import property is M2.3/#46's acceptance test, not yours to weaken).
- Pass 2 output per mark point is a binary verdict, plus the labeller's OWN judgment of the question's true type — that drives stratification, because the pipeline's question_type is unreliable (hardcoded to 'recall' on the det path).

THIS BATCH: batch=${batch}, pass=${pass}, target size=${size}.
BATCH WORKSPACE (agent-writable): ${batchDir}/ — manifest.json, one input form per leaf, qa/ for QA output. mkdir -p as needed. Write NOTHING anywhere else; never git-add or commit from this workflow.
LABEL STORE (HUMAN-writable, agent READ-ONLY): ${ROOT}/eval/labels/<paper_id>/{transcription,marking}.jsonl plus a manifest — append-only JSONL with a hash chain so post-hoc edits are detectable. It may not exist yet (M2.3/#46 open at time of writing): its absence means no labels exist, not an error.
The 'lemely label <paper_id>' command is M2.3/#46 and may not have landed — check before assuming. If it exists, the prepared forms should feed it; if not, the forms must be self-contained static files (markdown or HTML) a human can work through in an editor/browser, and the manifest must say which of the two applies.

SPLIT DISCIPLINE (non-negotiable):
- Select from the train/dev split ONLY. The test split is NEVER read, listed, rendered, or referenced by this workflow — no exceptions, no authorisation tokens here.
- The split field mechanism is M0.7a/#31 and the frozen split membership is M0.7b/#57 + H4/#49 (human approval). If a candidate leaf has NO recorded split assignment, DO NOT select it — exclude it with reason 'no-split-assignment'. Never guess a split.
STANDING RULES: never commit, never push, never close or reopen GitHub issues. H-numbered issues are human-only: H4/#49 (split approval), H7/#51 (10% re-label sample), H8/#52 (judgment adjudication) — queue work FOR them, never do them. tests/fixtures/real-papers/*.pdf contains a minor's real handwritten exam scripts — the forms may reference these files by local path for the human, but never redistribute, upload, or attach the scans to anything outward-facing.
`

// ---------------------------------------------------------------- schemas
const SELECT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          paper_id: { type: 'string' },
          question_id: { type: 'string', description: 'The leaf question id' },
          parent_id: { type: 'string', description: 'Parent question id, empty string for top-level leaves or where M0.8 has not landed' },
          split: { type: 'string', enum: ['train', 'dev'], description: 'The RECORDED split. test is unselectable by construction; no-assignment leaves are excluded, never guessed' },
          parse_path: { type: 'string', enum: ['det', 'gemini', 'unknown'], description: 'Which parser produced this scheme — both paths must be covered in the batch' },
          stratum: { type: 'string', description: 'Stratification bucket. Pass 2: the labeller-assigned type from the pass-1/pass-2 protocol where available; otherwise structural stratum (paper, mcq/theory, parse path) — never the pipeline’s unreliable question_type' },
          source_paths: { type: 'array', items: { type: 'string' }, description: 'Absolute paths to the scan/scheme material the form will be built from' },
        },
        required: ['paper_id', 'question_id', 'parent_id', 'split', 'parse_path', 'stratum', 'source_paths'],
      },
    },
    stratification_table: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { stratum: { type: 'string' }, count: { type: 'integer' } },
        required: ['stratum', 'count'],
      },
    },
    already_labelled_skipped: { type: 'integer', description: 'Leaves excluded because they already have a label for this pass, or sit in a prior batch manifest for this pass' },
    excluded: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { question_id: { type: 'string' }, reason: { type: 'string' } },
        required: ['question_id', 'reason'],
      },
      description: 'Every candidate rejected, with reason (no-split-assignment, test-split, already-labelled, unreadable-source, ...)',
    },
    manifest_path: { type: 'string', description: 'Absolute path of the manifest.json written to the batch workspace' },
    labelled_so_far_this_pass: { type: 'integer', description: 'Total distinct leaves across ALL papers that already have a label for this pass in eval/labels/ (0 if the store does not exist yet)' },
    notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['items', 'stratification_table', 'already_labelled_skipped', 'excluded', 'manifest_path', 'labelled_so_far_this_pass', 'notes'],
}

const PREP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    prepared: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          question_id: { type: 'string' },
          form_path: { type: 'string', description: 'Absolute path of the rendered input form' },
          model_output_hidden: { type: 'boolean', description: 'true only if you verified NO pipeline transcription, marks, confidence, or triggers appear anywhere in the form' },
        },
        required: ['question_id', 'form_path', 'model_output_hidden'],
      },
    },
    failures: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { question_id: { type: 'string' }, reason: { type: 'string' } },
        required: ['question_id', 'reason'],
      },
    },
  },
  required: ['prepared', 'failures'],
}

const VALIDATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    valid: { type: 'array', items: { type: 'string' }, description: 'question_ids whose form carries every required field' },
    invalid: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          question_id: { type: 'string' },
          missing_fields: { type: 'array', items: { type: 'string' } },
          blindness_breach: { type: 'string', description: 'Empty string if none; otherwise exactly what model output leaked into the form' },
        },
        required: ['question_id', 'missing_fields', 'blindness_breach'],
      },
    },
    checked_fields: { type: 'array', items: { type: 'string' }, description: 'The field list you validated against (must include split, paper_id, question_id, parent_id, parse_path, stratum, pass)' },
  },
  required: ['valid', 'invalid', 'checked_fields'],
}

const QA_COMPLETENESS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    label_store_exists: { type: 'boolean' },
    files_checked: { type: 'array', items: { type: 'string' } },
    rows_checked: { type: 'integer' },
    schema_complete: { type: 'boolean', description: 'Every row carries the fields spec section 6 requires for its pass' },
    hash_chain_intact: { type: 'boolean', description: 'Every row’s hash links to its predecessor; a broken chain means a post-hoc edit and is a blocking finding' },
    append_only_respected: { type: 'boolean' },
    defects: { type: 'array', items: { type: 'string' }, description: 'Each defect with file, line/row number, and what is wrong. NEVER fix a defect by writing to the label store — report only' },
  },
  required: ['label_store_exists', 'files_checked', 'rows_checked', 'schema_complete', 'hash_chain_intact', 'append_only_respected', 'defects'],
}

const QA_AGREEMENT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    pass1_pass2_consistency: { type: 'number', description: 'Fraction of pass-2 rows whose referenced transcription matches the labeller’s own pass-1 row (-1 if not computable, with why in caveats)' },
    self_agreement: { type: 'number', description: 'Agreement on the H7/#51 re-labelled 10% sample where one exists (-1 if no re-labelled sample exists yet)' },
    n_leaves_compared: { type: 'integer' },
    method: { type: 'string', description: 'Exactly how agreement was computed (per mark point? per leaf? which denominator?)' },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['pass1_pass2_consistency', 'self_agreement', 'n_leaves_compared', 'method', 'caveats'],
}

const QA_JUDGMENT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    judgment_questions: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          question_id: { type: 'string' },
          paper_id: { type: 'string' },
          issue: { type: 'string', description: 'The CAIE judgment call the labeller flagged or the labels imply (ECF, ambiguous ownership of a mark point, alternative-method acceptance, ...)' },
          suggested_h8_entry: { type: 'string', description: 'One paragraph ready to paste into H8/#52 for the human to adjudicate. Queue it — NEVER post it to the issue or adjudicate it yourself' },
        },
        required: ['question_id', 'paper_id', 'issue', 'suggested_h8_entry'],
      },
    },
    count: { type: 'integer' },
  },
  required: ['judgment_questions', 'count'],
}

const SUMMARY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    usable: { type: 'boolean', description: 'Is this batch (prepared forms, or QA’d labels) fit for its purpose?' },
    unusable_reason: { type: 'string', description: 'Empty string when usable; otherwise the plain-language reason and what the human must do about it' },
    batch_leaves: { type: 'integer', description: 'Leaves in this batch (selected, or QA-checked)' },
    labelled_leaves_total: { type: 'integer', description: 'Distinct leaves labelled across the whole programme so far in this pass (0 if the label store does not exist)' },
    target_leaves: { type: 'integer', description: 'The programme target: 300' },
    coverage_summary: { type: 'string', description: 'Progress toward ~300 distinct leaves across ~7-8 real papers, and what strata are under-covered' },
    agreement_summary: { type: 'string', description: 'The agreement figures with their n, or "not computable yet: <why>"' },
    questions_for_human: { type: 'array', items: { type: 'string' }, description: 'Everything the human must decide or do next: label the forms at <path>, adjudicate the queued H8 items, approve the split (H4), re-label the H7 sample, ...' },
    next_batch_recommendation: { type: 'string', description: 'What the next batch should target (strata, papers, size), grounded in the coverage gaps' },
  },
  required: ['usable', 'unusable_reason', 'batch_leaves', 'labelled_leaves_total', 'target_leaves', 'coverage_summary', 'agreement_summary', 'questions_for_human', 'next_batch_recommendation'],
}

// ---------------------------------------------------------------- prepare path
let selection = null
let prepResults = []
let qaResults = { completeness: null, agreement: null, judgment: null }

if (!qaMode) {
  phase('Select')
  log(`accuracy-label-batch: selecting up to ${size} leaves for pass ${pass}`)

  selection = await agent(`${GROUND}
You are the SELECTOR. Choose up to ${size} distinct leaf questions for this batch and write ${batchDir}/manifest.json.
1. Enumerate candidates: the labelling corpus is real papers (spec section 6 targets ~300 leaves over ~7-8 real papers). Look at what exists: eval/labels/ (may be absent), tests/golden/, tests/fixtures/real-papers/, outputs/schemes/, and anything the M2.1 corpus restoration has added. If the restored corpus is thin, select what genuinely exists and say so in notes — never pad with invented ids.
2. Apply SPLIT DISCIPLINE from GROUND: train/dev only; no recorded split assignment means excluded with reason 'no-split-assignment'.
3. Skip anything ALREADY labelled in pass ${pass}: read every eval/labels/<paper>/${pass === 1 ? 'transcription' : 'marking'}.jsonl that exists, and every prior manifest under ${ROOT}/BUILD/labelling/*/pass-${pass}/manifest.json. Count skips in already_labelled_skipped.
${pass === 2 ? '4. PASS-2 PREREQUISITE: a leaf is only selectable for pass 2 if the SAME labeller’s pass-1 transcription row for it exists in eval/labels/ — pass 2 is marked against the labeller’s own transcription. No pass-1 row, no pass-2 selection: exclude with reason "no-pass1-transcription".' : '4. This is pass 1: the mark scheme must NOT appear in source_paths — scan region material only.'}
5. STRATIFY so both parse paths (det and gemini) are covered and strata are balanced; the stratum field follows the schema's rule (labeller-assigned type where it exists, structural stratum otherwise — never the pipeline's question_type, which is hardcoded 'recall' on the det path).
6. Write manifest.json to ${batchDir}/ containing: batch id, pass, the items array, the stratification table, and which form-delivery mechanism applies ('lemely label' if M2.3/#46 has landed, static files otherwise).
Selecting FEWER than ${size} because honest candidates ran out is a correct outcome — record why in notes.`,
    { label: 'select', phase: 'Select', model: 'sonnet', agentType: 'accuracy-labeller', schema: SELECT_SCHEMA })

  if (!selection || selection.items.length === 0) {
    log('accuracy-label-batch: selection returned nothing usable — going straight to Summarise so the blocker is written up for the human.')
  } else {
    log(`accuracy-label-batch: selected ${selection.items.length} leaves (${selection.already_labelled_skipped} already-labelled skipped, ${selection.excluded.length} excluded). Manifest: ${selection.manifest_path}`)

    phase('Prepare')
    // Chunk the items so the agent count stays bounded: at most 4 chunks, 2 stages each.
    const CHUNKS = 4
    const items = selection.items
    const chunkSize = Math.ceil(items.length / CHUNKS)
    const chunks = []
    for (let i = 0; i < items.length; i += chunkSize) chunks.push(items.slice(i, i + chunkSize))
    if (items.length > CHUNKS) {
      log(`accuracy-label-batch: capping Prepare parallelism — ${items.length} items grouped into ${chunks.length} chunk(s) of up to ${chunkSize} so the workflow stays under its agent budget.`)
    }

    prepResults = await pipeline(
      chunks,
      async (chunk) => {
        if (!chunk || chunk.length === 0) return null
        return agent(`${GROUND}
You are a FORM RENDERER for pass ${pass}. For each item below, render a self-contained labeller input form into ${batchDir}/ named form-<question_id>.md (or feed 'lemely label' if the manifest says that mechanism applies).
THE ITEMS: ${JSON.stringify(chunk)}
Each form must contain: the header fields (batch=${batch}, pass=${pass}, paper_id, question_id, parent_id, split, parse_path, stratum), the material the protocol allows for pass ${pass} (${pass === 1 ? 'the scan region ONLY — reference the local scan path and reproduce the question text; NO mark scheme' : 'the mark scheme for this leaf PLUS the labeller’s own pass-1 transcription copied verbatim from eval/labels/<paper_id>/transcription.jsonl'}), and the blank answer section the human fills in (${pass === 1 ? 'their transcription of the candidate’s answer' : 'a binary verdict per mark point and their own judgment of the question’s true type'}).
ABSOLUTE RULE: no pipeline output anywhere in any form — no model transcription, no awarded marks, no confidence, no triggers. Grep your own rendered forms for leakage before returning and set model_output_hidden accordingly. NEVER pre-fill any answer section, not even as an "example".
An item whose source material is missing or unreadable goes in failures with the reason — do not fabricate content.`,
          { label: `prepare-${chunk[0].question_id}`, phase: 'Prepare', model: 'sonnet', agentType: 'accuracy-labeller', schema: PREP_SCHEMA })
      },
      async (prep) => {
        if (!prep || !prep.prepared || prep.prepared.length === 0) return prep
        return agent(`${GROUND}
You are the FORM VALIDATOR. The renderer claims these forms are ready: ${JSON.stringify(prep)}
Open every form_path and verify: (a) every required header field is present and non-empty — split, paper_id, question_id, parent_id, parse_path, stratum, pass; (b) the pass-${pass} blindness rule holds (${pass === 1 ? 'no mark scheme content' : 'no pipeline transcription'} and no model output of any kind — grep for marks/awarded/confidence/triggers/transcription-by-model); (c) the answer section is BLANK. Report per-form verdicts; put any leakage verbatim in blindness_breach. Do not edit the forms — a bad form is reported, and the summariser decides.`,
          { label: 'validate-forms', phase: 'Prepare', model: 'sonnet', schema: VALIDATE_SCHEMA })
      },
    )
    const nullPrep = prepResults.filter(r => r === null || r === undefined).length
    if (nullPrep > 0) log(`accuracy-label-batch: ${nullPrep} prepare/validate chunk(s) returned null — those items are unprepared and the summariser will be told.`)
  }
} else {
  // ---------------------------------------------------------------- qa path
  phase('QA')
  log(`accuracy-label-batch: QA mode — verifying human-returned labels for batch ${batch}, pass ${pass}. No Select/Prepare in this mode.`)

  const QA_COMMON = `${GROUND}
QA MODE: the human has (supposedly) returned labels. The label store is READ-ONLY to you: ${ROOT}/eval/labels/. The batch manifest, if this batch was prepared by this workflow, is at ${batchDir}/manifest.json — use it to know which leaves belong to this batch. Write your QA output under ${batchDir}/qa/ only. If the label store or the manifest does not exist, that IS your finding — report it, do not reconstruct either.`

  const qaRaw = await parallel([
    () => agent(`${QA_COMMON}
YOUR CHECK: schema completeness and tamper evidence. Validate every relevant row in eval/labels/**/{transcription,marking}.jsonl against the spec-section-6 shape for its pass, verify the hash chain row by row (each row's hash must commit to its predecessor), and confirm the files are append-only relative to any earlier QA snapshot under BUILD/labelling/*/qa/. A broken chain or an edited row is a BLOCKING defect: report it with file and row number.`,
      { label: 'qa-completeness', phase: 'QA', model: 'sonnet', agentType: 'accuracy-labeller', schema: QA_COMPLETENESS_SCHEMA }),
    () => agent(`${QA_COMMON}
YOUR CHECK: agreement. Compute (a) pass-1/pass-2 consistency — does each marking row reference a transcription row that exists and belongs to the same labeller pass-1 output; (b) self-agreement over the H7/#51 re-labelled 10% sample IF one exists (look for duplicate labelling of the same leaf separated in time within the JSONL; if none exists, self_agreement=-1 and say the H7 sample has not been done — do not create one). State your method and denominator exactly; collapse to distinct leaves.`,
      { label: 'qa-agreement', phase: 'QA', model: 'sonnet', agentType: 'accuracy-labeller', schema: QA_AGREEMENT_SCHEMA }),
    () => agent(`${QA_COMMON}
YOUR CHECK: judgment questions for H8/#52. Scan the returned labels (and any free-text labeller notes in them) for CAIE judgment calls a labeller cannot settle alone: error-carried-forward, alternative methods, ambiguous mark-point ownership, sig-fig/unit acceptance. Draft each as a ready-to-paste H8 entry and write the queue to ${batchDir}/qa/h8-queue.md. NEVER post to issue #52, never answer the judgment questions yourself — H8 is a human task.`,
      { label: 'qa-judgment', phase: 'QA', model: 'sonnet', agentType: 'accuracy-labeller', schema: QA_JUDGMENT_SCHEMA }),
  ])
  qaResults = { completeness: qaRaw[0], agreement: qaRaw[1], judgment: qaRaw[2] }
  const failedQa = ['completeness', 'agreement', 'judgment'].filter((k) => !qaResults[k])
  if (failedQa.length > 0) log(`accuracy-label-batch: QA agent(s) failed: ${failedQa.join(', ')} — the summariser must treat those checks as NOT DONE, not as passed.`)
}

// ---------------------------------------------------------------- Summarise
phase('Summarise')
log('accuracy-label-batch: summarise — one opus agent writes the human-facing verdict')

const summary = await agent(`${GROUND}
You are the SUMMARISER — the last honest voice before the human reads this. Report what happened to batch ${batch} pass ${pass} in mode=${qaMode ? 'qa' : 'prepare'}, against the programme target of ~300 distinct labelled leaves (M2.4/#47) with a published stratification table and self-agreement figure.

${qaMode
    ? `QA RESULTS:
- completeness/hash-chain: ${JSON.stringify(qaResults.completeness)}
- agreement: ${JSON.stringify(qaResults.agreement)}
- judgment queue: ${JSON.stringify(qaResults.judgment)}
A null result above means that check DID NOT RUN — treat it as not done, never as passed.`
    : `SELECTION: ${JSON.stringify(selection)}
PREPARE/VALIDATE RESULTS (chunked): ${JSON.stringify(prepResults)}
A null above means that chunk was neither prepared nor validated.`}

Rules for your verdict:
- usable=false whenever: (prepare mode) any validated form shows a blindness breach, or fewer than half the selected items produced valid forms, or selection itself failed; (qa mode) the hash chain is broken, schema_complete is false, or a QA check did not run. State the reason plainly — the human acts on your sentence, not on the JSON.
- Count coverage honestly: labelled_leaves_total comes from the label store (0 if it does not exist yet); this workflow NEVER produced a label, so prepared forms count toward coverage only once the HUMAN returns them.
- questions_for_human must be complete and actionable: where the forms are, which H-issues (#49 H4, #51 H7, #52 H8) are waiting on them, and any defect they must resolve.
- Recommend the next batch from the stratification gaps (under-covered strata, missing parse path, papers with no labels).
Also append one short dated entry describing this batch run to ${batchDir}/SUMMARY.md (create it if absent) so the human has a file to read, using bash date for the date.`,
  { label: 'summarise', phase: 'Summarise', schema: SUMMARY_SCHEMA })

if (!summary) {
  log('accuracy-label-batch: summariser returned null — returning the raw phase outputs so nothing is lost.')
  return {
    ok: false,
    error: 'summarise-failed',
    batch,
    pass,
    mode: qaMode ? 'qa' : 'prepare',
    selection,
    prepare: prepResults,
    qa: qaResults,
  }
}

log(`accuracy-label-batch: ${summary.usable ? 'batch USABLE' : `batch UNUSABLE — ${summary.unusable_reason}`}; coverage ${summary.labelled_leaves_total}/${summary.target_leaves} labelled leaves so far.`)

return {
  ok: true,
  batch,
  pass,
  mode: qaMode ? 'qa' : 'prepare',
  usable: summary.usable,
  summary,
  selection,
  prepare: prepResults,
  qa: qaResults,
  batch_dir: batchDir,
}
