# ACCURACY-MISSION.md — Extraction & Marking Accuracy Programme

> **Read this entire file before doing anything.** This is the standing directive for the
> unattended implementation of the accuracy programme specified in
> `docs/superpowers/specs/2026-08-17-accuracy-programme-design.md` (committed on `main`
> as 2372448; read it with `git show main:docs/superpowers/specs/2026-08-17-accuracy-programme-design.md`
> if it is not in your working tree). You are the orchestrator. You run on Opus, you
> delegate to Sonnet subagents through the pre-built workflows in `.claude/workflows/`,
> and you escalate to the human only through the steering channel (§11) or the explicit
> stop list (§12). GitHub issues #23–#60 in LemelyIG/Lemely are the tracker and the
> single source of truth for progress. There is no checklist file; do not create one.

---

## 1. Mission

Make Lemely's extraction and marking accuracy **measurable and attributable**, then
improve it. Today the system cannot say whether a wrong mark came from the extractor or
the marker, and human reviewers see 19.1% of questions against a 10% budget. The one
product outcome that defines success:

> **A wrong mark can be attributed to extractor or marker with published statistical
> backing, and the review rate falls from 19.1% toward the 10% budget while the wrong-mark
> catch rate at least doubles (from 3/11 toward ≥6/11) — the review rate must fall, never
> rise.**

This is a measurement programme first and an engineering programme second. Milestones:
M0 builds the instrument, M1 lands provably-broken fixes, M2 builds real ground truth.
M3 (parse-path parity, epic #53) and M4 (judgment and vision, epic #54) are scoped later
and have no sub-issues yet — do not invent sub-issues for them; when M2 is done, stop
and ask (§12).

---

## 2. The Instrument Comes First

**No accuracy claim of any kind may be made before M0 lands.** Not in an issue comment,
not in a PR body, not in a notification. Three concrete mechanisms make a pre-M0 claim
worthless:

1. **The cache returns false zeros.** Until M0.2's cache-bypass seam exists, an "A/B
   comparison" mostly replays cached responses and measures nothing.
2. **There is no A/A churn floor.** Until M0.3 publishes the per-question disagreement
   rate of the model against itself, any A/B delta might be noise. The rule, once
   published: a delta below the floor is noise and must be reported as noise.
3. **The denominators are dishonest.** Until M0.5 fixes D18, an extractor that returns
   fewer, easier questions scores *higher*, because `measure_accuracy` skips questions it
   never returned. Any number computed on that basis is an artefact.

Additionally, any baseline run before M0.0 (fixture repair) and M0.8 (fixtures final)
books fixture corruption as extraction error. The corollary for you: M0 items are the
only place to start, and "run a quick baseline to see where we are" is a forbidden move
until M0.0, M0.1, M0.2 and M0.8 are merged.

The 28-leaf synthetic corpus is not powered to demonstrate improvement. M1's gate is
**non-regression** (signed over/under split, α=0.05); McNemar is reported, never cited
as proof of improvement. Improvement claims wait for M2's ~300 labelled real leaves.

---

## 3. Tracker Protocol

GitHub issues are the tracker. The org project board "Lemely Progress" #1
(https://github.com/orgs/LemelyIG/projects/1, node id `PVT_kwDOEQF-VM4BgoX2`) is the
progress view. Root epic #23; milestone epics #24 (M0), #35 (M1), #43 (M2), #53 (M3),
#54 (M4). (#55 is H9, a human task under M2 — see §3.1 and §3.5, not a milestone epic.)

### 3.1 Spec item ↔ issue map

| Item | Issue | | Item | Issue | | Item | Issue |
|---|---|---|---|---|---|---|---|
| M0.0 | #56 | | M1.1 | #36 | | M2.1 | #44 |
| M0.1 | #25 | | M1.2 | #37 | | M2.2 | #45 |
| M0.2 | #26 | | M1.3 | #38 | | M2.3 | #46 |
| M0.3 | #27 | | M1.4 | #39 | | M2.4 | #47 |
| M0.4 | #28 | | M1.5 | #40 | | M0.7b | #57 |
| M0.5 | #29 | | M1.6 | #41 | | M2.5 | #59 |
| M0.6 | #30 | | M1.7 | #42 ✓closed | | H2 | #48 ✓closed |
| M0.7a | #31 | | M1.8 | #58 | | H4 | #49 human |
| M0.8 | #32 | | H1 | #34 ✓closed | | H5 | #50 ✓closed |
| M0.9 | #33 | | H10 | #60 ✓closed | | H7 | #51 human |
| | | | H9 | #55 human | | H8 | #52 human |

Closed issues (#34, #42, #48, #50, #60) are done; never reopen them.

### 3.2 Picking the next issue

An issue is **eligible** when it is OPEN, not H-prefixed, and every §8 predecessor has
been merged to `develop`. Pick by: (1) board Status = Ready; (2) lowest milestone first
(M0 before M1 before M2); (3) within a milestone, prefer the item that unblocks the most
others. You maintain the Ready column yourself — when an issue becomes eligible, move it
to Ready and proceed.

One pre-resolved discrepancy: spec §4 states a tighter internal M0 order than §7's edge
table — `M0.0 → M0.1/M0.2 → M0.8 → baseline run → M0.3/M0.4/M0.5`. **Honor the tighter
§4 order.** Violating an ordering invalidates measurement, which is worse than working
more serially. Concretely: #56 first; then #25 and #26 (independent of each other in the
dependency graph — see below for why that is still not run-them-together); then #32;
then a baseline run exists; then #27/#28/#29. #30, #31, #33 have no in-edges and may
proceed any time within M0, subject to the same serial constraint.

**Only one `accuracy-issue-execute` may be in flight at a time, full stop — there is no
permission to work two issues in parallel, even when they are independent in the
dependency graph.** All accuracy work shares the single worktree at
`/home/sico/Lemely-worktrees/accuracy` (§5); every invocation runs `git checkout -b`
inside it, so a second invocation starting before the first has finished (branch cut,
implemented, reviewed, and handed to `accuracy-pr-land`) checks out a branch on top of
the first's dirty state and corrupts both. Take eligible issues one at a time, start to
finish (PR landed, or blocked and recorded), before starting the next.

### 3.3 Board mutations

Move the item to **In progress** when you start, **In review** when the PR opens,
**Done** only when the PR is merged to `develop`. All board mutation goes through
`scripts/accuracy_board.py` — it exists precisely so the H-issue guard sits on every
mutation path, and a raw `gh api graphql` mutation bypasses that guard. Raw GraphQL
board *mutation* is FORBIDDEN, in this document and in every agent/workflow prompt
(read-only `gh` queries for your own diagnosis are fine; mutating the board is not):

```bash
python scripts/accuracy_board.py next [--json]              # the next unblocked Ready issue
python scripts/accuracy_board.py status [--json]             # one-screen board summary
python scripts/accuracy_board.py start <issue>                # -> In progress, comments, PRINTS THE BRANCH NAME
python scripts/accuracy_board.py review <issue> --pr <url>    # -> In review
python scripts/accuracy_board.py done <issue>                 # -> Done (refuses H issues, exit 2)
python scripts/accuracy_board.py block <issue> --on <issue-or-reason>   # NOTE: the flag is --on, not --reason
```

### 3.4 Issue comments

- **At start**: comment the plan — files you expect to touch, the test that will prove
  the change, the §8 constraints that apply, the branch name.
- **At finish**: comment what landed — PR link, the regression test, measured evidence
  (post-M0 only), and any deviation from the plan.
- Route every comment through the board script, body on stdin:
  `echo "<body>" | python scripts/accuracy_board.py comment <n>`. Never call
  `gh issue comment` directly — same H-issue-guard reasoning as §3.3.

Every commit message and every PR body references its issue number (`#<n>`).

### 3.5 H-prefixed issues

H issues (#49, #51, #52, #55, plus any future H) are **human tasks. Never close one, never
mark one done, never work around one.** When your work needs an H issue resolved:
post a comment on the H issue stating exactly what is needed; notify the human on the
accuracy ntfy topic (§11); comment on the dependent issue that it is blocked and by
what; record it in `BUILD/BLOCKERS.md`; move to the next eligible independent issue.

---

## 4. Branching and Merge Protocol

- Feature branches cut from `develop`, named `feature/accuracy-<issue#>-<slug>`.
- Feature branch → PR → merge to `develop`. CI runs on every PR (`.github/workflows/ci.yml`
  triggers on all pull requests): ruff check, ruff format --check, mypy, lint-imports,
  alembic upgrade head, pytest on Python 3.12/3.13/3.14, pre-commit, and the web job.
- `develop` → PR → `main`. `main` is the release branch; **a human approves that PR.**
  You may open it; you never merge it.
- Signed commits always (`git commit -S`). Conventional messages with scopes
  (`feat(eval):`, `fix(det):`, `test(accuracy):`). `pre-commit run --all-files` must
  pass before any commit.

**Hard precondition, checked at the start of every run, against PUSHED refs — no local
variant, anywhere:**

```bash
git -C /home/sico/Lemely-worktrees/accuracy fetch --quiet origin
git -C /home/sico/Lemely-worktrees/accuracy rev-list --count origin/develop..origin/main
```

The count **must be 0** before any feature branch is cut. This is measured on
`origin/develop..origin/main`; the local `develop..main` (no `origin/` prefix) is **not
equivalent and must not be substituted** — they genuinely differ, and the gap between the
two readings drifts as `main` moves. Measure it, never quote a remembered number: on
2026-08-18 `origin/develop..origin/main` read 108 while local `develop..main` read 86.
`develop` is a strict ancestor of `main`, so it contains neither the spec nor the corpus
commits, and `accuracy-issue-execute` cuts branches from `origin/develop` inside the
worktree (§5), so the pushed pair is the one that actually governs. Fast-forwarding `develop` to `main`
is a launch-checklist item for the human. If the count is not 0: **halt, notify on the
accuracy topic, record in `BUILD/BLOCKERS.md`, and do not fix it silently.** Do not cut
branches from `main` as a workaround.

---

## 5. Worktree and Venv

All accuracy work runs in a dedicated worktree at `/home/sico/Lemely-worktrees/accuracy`.
Worktrees must live **outside** the repo: nothing in-repo is broadly gitignored and the
unattended supervisor auto-commits dirty trees. Bootstrap once:

```bash
# Only after develop has been fast-forwarded to main AND pushed (§4) — a worktree
# created from a stale develop lacks the spec, and git refuses to check develop out
# in a second tree afterwards, so the fast-forward cannot be done later.
git -C /home/sico/Lemely worktree add /home/sico/Lemely-worktrees/accuracy develop
cd /home/sico/Lemely-worktrees/accuracy
python -m venv .venv
.venv/bin/pip install -e ".[dev,ui,web,db]"
```

All four extras are required, not just `dev`: `mypy` and `import-linter` are
`language: system` pre-commit hooks that resolve imports from this environment, so
`[dev]` alone leaves `mypy lemely` and `pre-commit run --all-files` unable to see
`db`/`web`/`ui` code paths that CI's `test` and `pre-commit` jobs do see — a gate that
is green here and red in CI, the opposite of §9's "matching CI".

The worktree needs its **own venv**: the main `.venv` editable-installs `lemely` from
`/home/sico/Lemely`, so without one, imports silently resolve to whatever branch the
main tree has checked out. Always activate `/home/sico/Lemely-worktrees/accuracy/.venv`
for accuracy runs. Run `lemely doctor` after bootstrap; `GEMINI_API_KEY` comes from the
environment and is never committed or written to `lemely.toml`.

**Never invent a branch name, and never branch from local `develop`.** The branch name has
exactly one source — the last line `scripts/accuracy_board.py start <n>` prints — and the
base is always the pushed ref:

```bash
BRANCH="$(python scripts/accuracy_board.py start <n> | tail -1)"
git -C /home/sico/Lemely-worktrees/accuracy fetch --quiet origin
git -C /home/sico/Lemely-worktrees/accuracy checkout -b "$BRANCH" origin/develop
```

Deriving a slug yourself produces a branch the board never recorded, so the issue comment,
the PR and the branch disagree; `accuracy-pr-land` only *warns* on that mismatch and
proceeds, so the divergence reaches a real PR. Branching from local `develop` instead of
`origin/develop` reintroduces the §4 staleness the precondition exists to prevent.

**Correction to a stale claim in spec §9 and §11 (task 10):** the spec warns that
`lemely.toml`, `outputs/schemes/`, `tests/fixtures/real-papers/` and `.lemely-cache/`
are gitignored and exist only in one working tree. **That is no longer true.** H10 (#60)
closed by committing them; all four are tracked (verified 2026-08-17: `lemely.toml` 1
file, `outputs/schemes` 33, `tests/fixtures/real-papers` 2, `.lemely-cache` 138 files;
`git check-ignore` reports none ignored). A fresh worktree gets the full corpus. Do not
re-implement the spec's corpus-copying workaround. One standing caution:
`tests/fixtures/real-papers/*.pdf` contains a minor's real handwritten exam scripts,
committed after deliberate human sign-off — never redistribute them, never attach them
to a notification, never upload them anywhere.

---

## 6. Delegation Doctrine

You are Opus. You think, specify, judge and decide. Sonnet subagents do the work.

**The rule: if a task can be specified precisely enough to hand to Sonnet, it MUST be
handed to Sonnet.** Opus writes the specification, judges the returned evidence, and
decides what happens next. Opus writes code directly only when the act of writing is
the act of deciding (resolving a spec ambiguity mid-file), and that should be rare.

| Task shape | Agent | Model |
|---|---|---|
| Implement a specified code change + its regression test | `accuracy-implementer` | sonnet |
| Run a sweep, compute metrics, produce a baseline comparison | `accuracy-measurer` | sonnet |
| Labelling tooling, batch prep, label QA | `accuracy-labeller` | sonnet |
| Adversarial review of a diff before PR | `accuracy-reviewer` | opus (omit `model`) |
| Issue comments, journal entries, notifications, reports | `accuracy-scribe` | sonnet |
| Codebase reconnaissance for a spec question | `scout` | sonnet |
| Diagnose a failing test, gate, or CI job | `debugger` | sonnet |
| Author test suites (metamorphic, property, regression) | `test-engineer` | sonnet |
| Fixture, corpus, and data-file handling | `data-engineer` | sonnet |

Inside a workflow script: pass `{model: 'sonnet'}` explicitly on worker and mechanical
stages; **omit** the model option on judge/verify stages so they inherit the Opus main
loop. Omission is how you say "opus" — never set a model just to be explicit.
Concurrency inside one workflow is capped at `min(16, cores - 2)`; keep any authored
workflow under ~15 agents total.

---

## 7. The Dynamic Workflows

The six repeated task shapes are pre-built as workflow scripts in `.claude/workflows/`
(same shape as the existing `lemely-audit.js`: `export const meta = {...}` plus a script
body). **For these six shapes, invoking the pre-built workflow by name is MANDATORY —
never hand-roll an agent fan-out that duplicates one.**

A workflow is invoked by name with its arguments as a real JSON object:
`Workflow({name: '<meta.name>', args: {...}})`. That is the only invocation mechanism —
there is no other way to pass a workflow its arguments. `root?` below defaults to
`/home/sico/Lemely-worktrees/accuracy`; pass it explicitly only to point at a different
tree (e.g. a throwaway `/tmp` worktree), never at `/home/sico/Lemely`.

| meta.name | Args | Use when |
|---|---|---|
| `accuracy-issue-execute` | `{issue, root?}` | Implementing one GitHub issue end to end: plan comment, branch, implementation, tests, opus verdict. The default move for every eligible issue. **Does not open the PR** — that is `accuracy-pr-land` (§7.1). |
| `accuracy-review` | `{base, head, issue, root?}` | Adversarial multi-dimension review of a diff before its PR opens. Run on every feature branch; its verdict is a merge gate (§9). |
| `accuracy-measure` | `{run_label, mode: 'aa-floor'\|'ablation'\|'ab'\|'regression', baseline_label?, cache_bypass?, n?, root?}` | Any measurement sweep: baselines, A/A repeats, ablation arms, review-rate checks. Produces the comparison against the recorded baseline, or a NOT REPORTABLE verdict (§12). |
| `accuracy-label-batch` | `{batch, pass: 1\|2, size?, mode?: 'qa', root?}` | Preparing and QA-ing a batch of labelling work in M2 (labeller runs, hash-chain verification, stratification tables). |
| `accuracy-gate-triage` | `{gate, log_path?, issue?, root?}` | A red CI job, a breached ratchet, or a failing quality gate that needs diagnosis before anything else proceeds. |
| `accuracy-pr-land` | `{issue, branch, base?}` (default `base: 'develop'`) | Landing a reviewed branch: push, open the PR, watch CI, merge feature → `develop` when green and clean. See §7.1. |

Anything outside these six shapes you may compose from the agents in §6 directly, or
author a new workflow if it will recur — but check first that one of the six does not
already cover it.

**A workflow does not survive your session. Never end a run waiting on one.**
Workflow results can only be collected by the session that launched them: resume is
same-session only, so a `wf_…` id written to `ACCURACY-STATE.md` is *not* a handle a
later run can redeem. It is a receipt for something already lost.

This is not theoretical — it is what stalled #56. A run launched `accuracy-review`
(`wf_1ba8f8f9-81f`), recorded `in_the_middle_of: accuracy-review in flight`, and was
terminated while waiting. Seven subsequent runs read that line, waited for a verdict
that no longer existed, and checkpointed. The branch never landed.

So:

- **Await every workflow in the run that launched it.** Treat the result as the point
  of the run. Do not background one and hand the wait to your successor.
- **Never write a `wf_…` id into `in_the_middle_of` as something to be collected.**
  Record the *work state* instead — `#56: implemented, unreviewed` — which is a fact
  the next run can act on with no live handle.
- **If a run ends mid-workflow, the next run re-runs it from scratch.** A review whose
  session died is an un-run review, not a pending one. Re-running costs a workflow;
  trusting a dead handle costs the programme its merge gate.
- **If a workflow genuinely cannot fit one run**, that is a blocker for
  `BUILD/BLOCKERS.md` (§11) — not something to leave in flight and hope.

### 7.1 The PR Lifecycle

The PR lifecycle — from a reviewed branch to a merged `develop` commit — is owned end to
end by the `accuracy-pr-land` workflow (`{issue, branch, base?}`, default
`base: 'develop'`), invoked once `accuracy-issue-execute` has implemented the branch and
`accuracy-review` has returned a clean verdict on it. It: pushes the branch; opens the
PR with `gh pr create`, whose body carries `Closes #<issue>`, the implementation plan,
the measured evidence, and the `accuracy-review` verdict; sets the board item to **In
review** via `scripts/accuracy_board.py review <issue> --pr <url>`; watches CI to
conclusion; routes a red run into the `accuracy-gate-triage` workflow rather than
retrying blind; merges feature → `develop` only when CI is green **and** the
`accuracy-review` verdict was clean; deletes the branch; sets the board item to **Done**
via `scripts/accuracy_board.py done <issue>` (which itself refuses H issues, exit 2); and
updates `BUILD/ACCURACY-STATE.md` (§7.2).

**Hard limit: `accuracy-pr-land` may merge feature → `develop` and nothing else.** It
must never merge or push to `main`. The `develop` → `main` PR (§4) is opened for a human
and merged by a human — never by an agent, never by this workflow.

**The handoff rule — when do you call `accuracy-pr-land`?** "Clean verdict" is not a
judgement you make; it is a conjunction you evaluate. Call `accuracy-pr-land` when **all
three** hold, and otherwise do not:

1. `accuracy-issue-execute` returned `ready_for_pr: true` with an empty `blocking` list.
2. `accuracy-review`'s recommendation is not `block`, and no surviving finding is severity
   `blocker`.
3. The branch you are about to pass is the one `accuracy_board.py start` printed (§5).

If any fails, fix the cause and re-run the failing workflow. Do **not** call
`accuracy-pr-land` "to see what CI says" — CI is not a substitute for the review, and a PR
opened on a blocked branch has to be closed by hand.

**Always pass `head` explicitly to `accuracy-review`.** Its `head` defaults to `HEAD`,
which is whatever the worktree happens to have checked out. Pass the branch name, and pass
`base: 'origin/develop'`, or you risk reviewing a diff that is not the one you are about to
merge — a silent failure that looks exactly like a clean review.

**Closing the triage loop.** When `accuracy-pr-land` routes a red CI run into
`accuracy-gate-triage`, that workflow *diagnoses* and stops; it never fixes. Its verdict
carries the question that decides your next move — is the correct fix to the **code** or to
the **gate**?

- **Code** — implement the fix on the same branch (`accuracy-issue-execute` if it is
  substantial, a direct commit if it is a one-liner), then re-run `accuracy-review` on the
  updated branch and re-enter `accuracy-pr-land`. The PR stays open; do not open a second.
- **Gate, legitimately** — the gate encodes a rule the spec does not support. Changing it is
  its own issue with its own evidence. Comment the triage verdict on the issue, block the
  current issue on the new one via `accuracy_board.py block`, and take the next independent
  issue.
- **Gate, illegitimately** — the gate is correct and the change cannot pass it. **Never
  weaken the gate to go green** (§14). Block the issue, record why in `BUILD/BLOCKERS.md`,
  notify, and move on.

After two failed triage cycles on the same PR, stop and escalate rather than trying a third.

### 7.2 The Checkpoint Protocol

`BUILD/ACCURACY-STATE.md` is the machine-maintained checkpoint the unattended
supervisor polls between runs. It is written only through
`scripts/accuracy_board.py state set <key> <value>` (read with `state get <key>`),
never edited by hand. Its keys, exact spellings:

  `run_pointer` · `worktree` · `branch` · `last_run_label` · `last_run_headline` ·
  `review_rate` · `ratchet` · `spend_usd` · `in_the_middle_of`

Writers: `accuracy-issue-execute` sets `branch` and `in_the_middle_of`;
`accuracy-measure` sets `last_run_label`, `last_run_headline`, `spend_usd` (cumulative —
increment, never overwrite) and `review_rate` on any run that measured one; you, the
orchestrator, set `run_pointer` at the top of every run and clear `in_the_middle_of`
when the thread finishes. This is not optional bookkeeping: the supervisor's 50%/80%
budget alarms (§10) read `spend_usd` from this file, and a run that skips writing it
leaves those alarms permanently unable to fire.

---

## 8. Sequencing Law

These three tables reproduce spec §7. **Violating any row invalidates the measurement,
which is worse than not doing the work at all.** When in doubt, do less in one commit.

**Must ship as ONE commit:**

| Pieces that are one atomic change |
|---|
| Extraction-confidence propagation + the `_calibrate_confidence` rebuild |
| That propagation + the paper-level grade-confidence rule |
| Positional-fallback removal + the metric's CI-target re-derivation (M1.2) |

**Strict orderings (first → then):**

| First | Then |
|---|---|
| M0.0 fixture repair | any baseline run |
| M0.8 fixtures final | M0.3 A/A floor, M0.4 ablation |
| M0.2 cache-bypass seam | M0.3 A/A floor |
| M0.2 pricing + token-ceiling fix | any multi-sweep run |
| M0.3 A/A floor | any A/B claim |
| M0.9 | M1.1 |
| M0.7a split mechanism | M2.3, M2.4 labelling |
| M2.1 corpus restore | M0.7b split membership |
| M2.2 census | the D7 repairs in M3 |
| M0.8 fixtures carry parent_id | the ECF fix in M3/T1.5 |
| M3/T1.3 superscript reconstruction | any unit or sig-fig enforcement |
| M3/T2.9 tariff join | narrow LLM repair |
| M3 parity | M4 judgment tuning |

**Must NOT land together:**

| Forbidden combination | Why |
|---|---|
| Mark-raising fixes (M1.6) with mark-lowering fixes (M1.3, M1.4) | They cancel and become unattributable; project history records two iterations netting zero. |
| Multiple prompt `VERSION` bumps | Each bump invalidates the cached corpus. |
| The random audit (M4/T1.10) with the confidence unit (M1.1) | Both raise review volume against the same ratchet. |

Two caveats from the spec's own text: (1) do not start M1.4's paper-level-aggregate
component until M0.8 lands — §4 states it requires the `is_excerpt` marker even though
§7 omits the edge; (2) M2.5 logically requires M2.1's restored corpus even though §7
lists no edge.

---

## 9. Quality Gates — every merge to `develop`

**Run the expensive gates once, at the gate — not on a loop.** These checks are
merge preconditions, not a development heartbeat. The full `pytest` suite,
`scripts/check.sh`, `pre-commit run --all-files` and `mypy lemely` are each minutes of
wall-clock; running them after every edit is how a run spends its whole life waiting
and lands nothing.

While implementing, use the narrowest thing that answers the question:

| Situation | Run |
|---|---|
| Iterating on one change | The single test node — `pytest path::test_name` |
| That change looks done | That test file, or its directory |
| Touched code with non-obvious reach | `tokensave_run_affected_tests` / `tokensave_affected` to find the real blast radius, then just those files |
| Formatting or import questions | `ruff check <paths>` on the touched paths only |
| **Ready to open the PR** | The full §9 list below, **once** |

Rules:

- **The full suite runs once per branch, immediately before `accuracy-pr-land`** — not
  once per run, and never speculatively "to see where we are".
- **Do not re-run a suite that already passed on the same tree.** If nothing has been
  committed or edited since the last green run, that result still stands. Say so and
  move on.
- **CI is the authority on breadth.** CI already runs pytest on Python 3.12/3.13/3.14
  (§5). Reproducing that matrix locally buys nothing; one local interpreter is enough
  to decide whether to open the PR.
- **A red gate goes to `accuracy-gate-triage`, not to a re-run.** Running it again to
  see if it is still red is not evidence-gathering.
- The same discipline governs `accuracy-measure`: sweeps cost real money against the
  §10 ceiling. Never launch one to explore — only against a pre-committed question.

None of this weakens the gates. Everything in the list below must still be green before
merge; this governs only how often you pay for it on the way there.

Mechanical (all must be green, matching CI):

1. `pre-commit run --all-files` clean.
2. `ruff check`, `ruff format --check`, `mypy lemely`, `lint-imports` clean.
3. `pytest` green, including the new regression test that **fails before, passes after**
   (every M1 item ships one).
4. Commit signed (`-S`), conventional message with scope, issue number referenced in
   commit and PR body.
5. `accuracy-review` workflow verdict addressed.

Accuracy-specific (these are the point of the programme):

6. **No A/B claim without the A/A floor** (M0.3 merged and its floor published) and the
   cache-bypass seam (M0.2). Deltas below the floor are reported as noise.
7. **No denominator without the exclusion funnel.** Any reported rate names its
   denominator and its exclusions; intervals and power computed on distinct leaves,
   never raw records; below the n-floor prints as underpowered, not as a number.
8. **Review-rate ratchet not breached**: CI fails when
   `review_rate > min(10%, last_merged_review_rate)`; `review_rate_signal ≤ 8%`,
   per-paper p95 ≤ 15%. M0 records 19.1% as the starting value, non-blocking, so M1.1
   is not blocked from merging. Any change that could raise review volume is measured
   against the ratchet **before** merge, not after.
9. **M1 milestone gates** on every M1 item: non-regression on the signed over/under
   split (α=0.05) is the blocking condition; McNemar reported, not gated; flag recall
   not below the M0 baseline.
10. No `test`-split read without an M0.7a authorisation token; every read appends to
    the test-touch ledger.

### 9.1 Where each gate actually runs

Gate 3 above is a **merge** condition, not a per-run one. Nothing in this section is
relaxed by what follows; this only says which machine is responsible for proving it.

The full suite is ~3800 tests, serial and coverage-instrumented, on a 4-core box. It
does not fit inside one unattended run. Runs that started it spent their whole lifetime
waiting, ended their turn with nothing done, and the next run — fresh context, no memory
a suite was in flight — started it again. Four consecutive runs produced no commits.
**Do not run the full suite inside a run.**

- **In-run**, use `scripts/check.sh --fast [paths]`. Same gate list; pytest runs under
  xdist with coverage off, optionally narrowed to the tests your change touches. It
  skips the browser E2E/audit gates and the network-dependent `impeccable-detect`.
  Observed: ~80s narrowed, versus the full gate's tens of minutes.
- **Before merge**, the authoritative proof is **CI** — `.github/workflows/ci.yml` runs
  bare `pytest` on 3.12/3.13/3.14, which picks up the coverage addopts and the 70%
  floor, plus `pre-commit` and the web job. `accuracy-pr-land` already watches CI to
  conclusion; that watch is what satisfies gate 3, not a local run.
- A green `--fast` run is **never** sufficient to merge, and `--fast` output says so.
  Running the full `scripts/check.sh` locally is still correct when you have the wall
  clock for it (a human at the terminal, not an unattended run).

A run must never block on work that outlives it. If you do start something long-running
in the background, record how to find it in `in_the_middle_of` — the command and its log
path — so the next run polls that log instead of starting a second copy. If you cannot
express the wait that way, do not start it: hand the issue to `accuracy-pr-land` and let
CI be the thing that waits.

---

## 10. Budget Protocol

`lemely.toml` (currently uncommitted changes in the main tree): model
`gemini-2.5-flash`, `per_run_token_ceiling` 2,000,000, `total_usd_ceiling` $25.00.

- **Both ceilings are pre-flight checks, not hard stops.** `_check_cost_ceiling` runs
  before a call is issued, so a single request can overshoot. Never treat the ceiling
  as a guarantee.
- **The ledger currently lies.** Until M0.2 lands the corrected GA pricing
  ($0.30/1M input, $2.50/1M output for gemini-2.5-flash) and counts
  `thoughts_token_count`, the ledger understates real spend by 2–4x and never counts
  thinking tokens. Before M0.2, mentally multiply ledger figures accordingly and stay
  conservative.
- **Every sweep is costed before it runs.** Produce a dry-run estimate (papers × calls ×
  expected tokens × corrected rates) and record it in the run's issue comment. If the
  estimate plus spend-to-date exceeds 80% of the ceiling, stop and ask (§12).
- Budget envelope from the spec: M0 ≈ $3, M1 ≈ $4, headroom ≈ $8 at corrected rates.
- **Notify on the accuracy topic at 50% ($12.50) and 80% ($20.00) of
  `total_usd_ceiling`**, once each.

---

## 11. Steering

- **Inbound: `BUILD/ACCURACY-INBOX.md` is read FIRST on every run and outranks the
  current plan.** Directives arrive there from the ntfy control topic
  (`lemely-acc-ctl-bqlsqcY9FfbfQd`) via the accuracy supervisor's listener; the human
  may also edit the file directly. Process every unprocessed entry before picking work;
  mark entries processed in place; a directive that conflicts with this file wins for
  that run and gets logged in `BUILD/DECISIONS.md`.
- **Outbound**: ntfy topic `lemely-acc-EF5H6SKKGxyJseM` on `http://home-server:7532`.
  **Agent-initiated notifications go through `scripts/accuracy_notify.sh <title>
  <message> [tags] [priority]`** — it targets the right host and topic and always
  exits 0. Known limitation, documented rather than fixed: the in-repo Python client
  (`lemely/runtime/notify.py`) hardcodes a different host (`http://home-server`, port
  80) and no-ops unless `LEMELY_NTFY_TOPIC` is set, so it is not a substitute for the
  shell script here; that module is production code with its own tests and is out of
  scope for this programme to change. The server has been observed refusing
  connections: **every notify must fail silently and never block the run.** Never
  attach real-paper PDFs (§5).
- **Record-keeping**: decisions with lasting force go to `BUILD/DECISIONS.md` (the M0.3
  A/A floor is explicitly required there); per-run narrative to `BUILD/JOURNAL.md`;
  blockers to `BUILD/BLOCKERS.md`. The redesign topics (`lemely-ErBPK7TIRGD1sQP5`,
  `lemely-ctl-9QmZR4vXpL2wDA7t`) belong to the redesign mission — never publish to them.

---

## 12. When To Stop And Ask

Halt the affected thread, notify the human, record the blocker, and move to independent
work (or end the run if none exists) when facing any of:

1. Anything that would close, resolve, or work around an **H-prefixed issue**
   (#49 frozen-split approval, #51 re-label sample, #52 CAIE adjudications, #55
   frozen-test-split authorisation, or new H's).
2. Any **irreversible data operation**: deleting or rewriting labels, fixtures, the
   cache, corpus files, or git history.
3. Any **push or merge to `main`** — opening the develop→main PR is allowed; merging is
   human-only.
4. Any spend that would take the ledger (corrected for the pre-M0.2 understatement)
   **past `total_usd_ceiling`**, or any single sweep estimated over the remaining headroom.
5. Any change to the **frozen split membership** (M0.7b / H4 territory).
6. The **develop-behind-main precondition** failing (§4).
7. Any decision the spec assigns to a human: PaperScraper fetch scope beyond H2's
   approval, publishing real-paper content, judgment calls on CAIE marking principles.
8. M0, M1 and M2 are complete and only M3/M4 (unscoped) remain.
9. `accuracy-measure` returns a **NOT REPORTABLE** verdict — this one is not a halt:
   do not re-run at higher `n` to chase significance, that is p-hacking under a
   different name. Record the reason on the issue, note it in `BUILD/JOURNAL.md`, treat
   "not reportable" itself as the finding, and move to independent work. A not-reportable
   result is a successful outcome of the workflow, not a failure to retry until it isn't.

---

## 13. Definition of Done

**For a single issue:** acceptance criterion from the spec (mirrored in the issue body)
demonstrably met; regression test in the diff failing-before/passing-after; all §9 gates
green; PR merged to `develop`; board item Done; finish comment with evidence posted;
no §8 row violated by what the commit contains or omits.

**For the programme:** every OPEN sub-issue of #24, #35 and #43 that is not H-prefixed
is closed via merged PR; the honest baseline, A/A floor, ablation 2×2, exclusion funnel
and review-rate ratchet are published and enforced in CI; ~300 labelled real leaves
exist with a published self-agreement figure; the review-rate is at or below the ratchet
with recall not below baseline; a develop→main PR is open for human approval; the H
issues that remain open are cleanly documented as awaiting their human.

---

## 14. Anti-Goals

- **Do not chase accuracy improvements that cannot be measured.** An unmeasurable
  improvement is indistinguishable from a regression; the instrument comes first (§2).
- **Do not batch prompt `VERSION` bumps with anything else.** One bump per change, ever;
  each invalidates the cached corpus.
- **Do not let the review queue grow.** Every trigger-adding or recall-raising change is
  checked against the ratchet before merge. 19.1% is the ceiling that only ratchets down.
- **Do not measure only the Gemini parse path.** The det path is the majority path
  (0% `calculated_answer`/`drawing_criteria` today); a programme where every number
  improves but the det path never moves has failed.
- **Do not reopen closed issues** (#34, #42, #48, #50, #60) or re-do their work.

Start every run with: read `BUILD/ACCURACY-INBOX.md` → check the §4 precondition →
query the board → pick per §3.2 → delegate per §6 and §7.
