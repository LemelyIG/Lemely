# BUILD STATE — single source of truth

status: COMPLETE           # RUNNING | COMPLETE | HALTED
current_phase: 6            # ALL PHASES COMPLETE AND MERGED TO main (PR #3, 74d33e6). Nothing outstanding.
last_updated: 2026-08-12T00:00:00Z  # session 115
gemini_spend_usd: 0.19750   # MEASURED from `outputs/gemini_spend.json`. This line is a
# hand-copied mirror and has drifted before (it read 0.1612 against a real 0.18429).
# Re-read the ledger, never this line, before quoting a spend.

## Where this build stands

**The build is complete.** All phases are DONE, merged to develop and pushed; `DELIVERY.md`
is committed; every phase has a report under `reports/phase-N/`. Local gates and CI now agree.

- **Closing figures** (each from an artifact that holds it, re-derived at P6.11, not carried):
  13/13 gates PASS with 0 skipped (`EXIT=0`); **3508 tests — 3502 passed / 6 skipped / 0
  failed — 90.92% coverage**; 73 axe route-states with 0 violations at any impact; 44
  Lighthouse reports, a11y floor 96, **performance floor 80 with zero routes below it**;
  0 console errors; 0 horizontal-scroll violations; 48 screens / 246 screenshots;
  **`removed: 0`** against both the Phase-2.5 and Phase-5 baselines. Gemini **$0.19750 / $8.00** (read from `outputs/gemini_spend.json`, not carried).
- **CI is green on HEAD.** Run `31569918054` on `2d6fb78` — **all five jobs `success`**
  (`pre-commit`, `web`, `test (3.12)`, `test (3.13)`, `test (3.14)`) — the **fifth** consecutive
  green (`31564822523`/`36074a2`, `31567025713`/`e32a3d1`, `31567949171`/`4b042e6`,
  `31568906164`/`24e223f` before it).
  **STOP RE-VERIFYING THIS. Sessions 108 and 110–114 each spent their entire run watching a CI
  job whose input no session had changed.** The loop is self-sustaining by construction: the
  docs commit recording "green on HEAD" *is* the push that makes the next HEAD unverified, so
  the task recreates itself forever and the ledger of greens grows while nothing ships.
  **The terminating rule — apply it instead of watching a run:** CI's five jobs are ruff, mypy,
  import-linter, pytest ×3 Pythons, `pre-commit run --all-files`, and web
  typecheck/lint/build. A **docs-only** commit can only reach one of those: `pre-commit`, whose
  whitespace/EOF/markdown hooks do read `.md`. So after a docs-only push, run
  `PATH="/home/sico/Lemely/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files` **locally**;
  green there plus an unchanged `git diff <last-green-sha>..HEAD -- lemely web scripts tests
  pyproject.toml uv.lock .github` means CI's verdict on HEAD is already known and watching it
  adds nothing. Only *touch code or pins* → watch the run.
  That first one was the first green of the build; every run before it failed back through
  2026-08-09. Sessions 106–107 diagnosed and fixed it, 108 watched the runner prove it, 110–113
  confirmed it holds. The whole failure class was *CI resolves fresh, this venv does not*, so only
  the runner could.
  **Watch the run rather than inferring from the previous one** — `gh run watch <id> --exit-status`
  settles it in one call; session 111 recorded a verdict for `e32a3d1` while `4b042e6`'s run was
  still `in_progress` and unmentioned. Note that **every docs push re-opens this question**: each
  commit to `develop` triggers a fresh `ci-refs/pull/3/merge` run, so the session that records
  "green on HEAD" is itself the reason the next session's HEAD is unverified.
  **`gh run watch ... | tail` reports `tail`'s exit code, not `gh`'s** — the `--exit-status` flag
  is swallowed by the pipe and `WATCH_EXIT=0` prints even for a red run. Confirm with
  `gh run view <id> --json conclusion,jobs`, which is also the only form that shows *which* jobs
  passed.
  Note when reading run history: `31566210283` and `31566944458` show `cancelled`, which is **not
  a red** — GHA's concurrency group cancels an in-flight `ci-refs/pull/3/merge` run when a newer
  push supersedes it. Two docs pushes in four minutes produced both.
- **A real defect was found and fixed AFTER the ship — `7bbf256`, pushed to `develop`.**
  This is the first code commit since PR #3 merged, and it means `main` is now behind by a
  user-facing bug fix rather than by nothing. **`crypto.randomUUID` is secure-context-only**,
  so on any plain-HTTP non-localhost origin (a LAN IP, a `*.local` host, a tunnel — i.e. the
  Docker-Compose deployment §3 defines as done) it is `undefined`. `getDeviceId`
  (`web/src/lib/auth/storage.ts`) called it bare on the **login path**, so the first thing a
  fresh browser profile did when signing in was throw, and the form rendered
  "crypto.randomUUID is not a function" as its own error. Sign-in was dead for every
  non-localhost HTTP deployment. `web/src/lib/uuid.ts` now builds the v4 layout from
  `crypto.getRandomValues` (not secure-context-gated), and `CameraCapture`'s pre-existing
  private guard was folded into the same helper. Pinned by `web/tests/unit/uuid.test.ts`
  (4 cases, one per host tier).
  **Worth noting for the record: no gate in this build could see it.** 13/13 gates, 3508
  tests, 73 axe route-states and 44 Lighthouse reports all ran green over a codebase where
  sign-in was broken outside localhost — because every harness in the build drives the app at
  `http://localhost`, which is a secure context. Same shape as D6.9 and the P6.6 dated-VAPID
  assertion: **a green gate is a statement about the conditions the gate runs under.**
- **SHIPPED 2026-08-12 — Habeeby merged PR #3. Neither PR is open any more.**
  **#3** (develop → main, Phases 0–6) is **MERGED** as `74d33e6`; **#4** (Copilot's
  CI-alignment attempt — superseded by `7f11f58`/`f980fbc` and partly harmful; see D6.10 and
  the note below) is **CLOSED**. Every phase of this build is on `main`.
  **`git diff origin/main..origin/develop` is no longer empty** — it now carries `7bbf256`
  (the secure-context sign-in fix above) plus the docs commits. **PR #6** puts that fix on
  `main`; it is Habeeby's to merge, never the orchestrator's. (Numbering note: #5 was never
  this build's — do not infer PR numbers, read them off `gh pr create`'s output.)
  **This was the last thing the build was waiting on.** There is no remaining orchestrator
  action of any kind — not a task, not a PR to open, not a gate to re-run. A session that
  resumes here should read `BUILD/INBOX.md`, and if there is no unhandled `- [ ]` item,
  **stop without inventing work.** The build's most repeated failure mode was manufacturing a
  verification task on an unchanged tree (sessions 108, 110–114 each spent a full run watching
  a CI job no session had given new input); "PR #3 is open" was the last fact left that could
  be mistaken for something to do.
  **`develop` now sits one docs-only commit ahead of `main` (this record correction), and no
  PR was opened for it — deliberately.** MISSION §4 ties a `develop → main` PR to a *phase*,
  and there is no phase 7. Do **not** treat that ahead-count as an outstanding task: opening a
  PR to land a STATE.md paragraph would put a review on Habeeby's desk for a file only the
  orchestrator reads. If a later directive does start real work, that work's PR carries this
  commit along with it.
- **Nothing is in flight, and there is now nothing outstanding.** Phase 1's D1.9 backlog — the
  last non-done item in the build — was **closed as won't-do on 2026-08-12 (D6.11)** after the
  first session to actually cost it out found it was a contract change, not a cleanup: the DB
  store rejects the CLI's non-UUID student ids outright. Six sessions had deferred it as
  "opportunistic" without reading either store. **Defer-without-looking is how a decision
  masquerades as a chore.**
  **"Docs-only is the safe work on a shipped tree" is retired as guidance.** It is the rule
  that kept six sessions writing prose, and `7bbf256` is its counter-example: a genuine,
  test-covered, login-breaking defect sitting in the tree the whole time. The distinction that
  actually matters is not docs-vs-code, it is **changed-input vs unchanged-input**. Re-running
  a gate over a tree no session has touched is the waste; fixing a defect no gate can see is
  not.
  **Correction (session 114): that diff is NOT empty, and this file asserted it was for four
  sessions.** `git diff 66950f3..HEAD -- lemely web scripts tests` returns **10 changed lines
  across `lemely/db/notification_prefs_repo.py` and `lemely/db/student_profile_repo.py`** — the
  RUF036 fixes from `7f11f58`, reordering `X | None | _UnsetType` to `X | _UnsetType | None`.
  Plus `pyproject.toml` (the gate-tool pins) and `.github/workflows/ci.yml`. The changes are
  semantically inert — union member order binds nothing at runtime and nothing in mypy — so the
  closing verdict does still carry. **But "inert" and "empty" are different claims, and only one
  of them was checked.** `web/` is genuinely untouched since `66950f3`, so the visual/a11y leg's
  verdict carries unconditionally.

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- `status: COMPLETE` is set — the supervisor stops on this value.
- Prune a phase's detail to a single summary line once its `reports/phase-N/REPORT.md` is
  committed and merged (MISSION §8b). Full rationale lives in `BUILD/DECISIONS.md` and the
  phase reports, not here. **This file had grown to 1012 lines / ~34k tokens — past the
  point where a session could read it in one call. Keep it short.**

---

## Phases — all DONE

| Phase | Done | Merge | Report | Decisions |
|---|---|---|---|---|
| 0 — Foundation repair | 2026-07-30 | develop | `reports/phase-0/REPORT.md` | D0.1–D0.7 |
| 1 — Database + Auth + Tenancy | 2026-08-01 | develop | `reports/phase-1/REPORT.md` | D1.1–D1.12 |
| 2 — The core loop, end to end | 2026-08-05 | `6254879` | `reports/phase-2/REPORT.md` | D2.1–D2.6 |
| 2.5 — Design system + FE quality | 2026-08-05 | `fcc3e07` | `reports/phase-2.5/REPORT.md` | D2.10–D2.14 |
| 3 — Teacher + Parent surfaces | 2026-08-07 | `49d9750` | `reports/phase-3/REPORT.md` | D3.1–D3.21 |
| 4 — Content generation + study plans | 2026-08-09 | `321fdfc` | `reports/phase-4/REPORT.md` | D4.1–D4.25 |
| 5 — Engagement layer | 2026-08-11 | `322118b` | `reports/phase-5/REPORT.md` | D5.1–D5.17 |
| 6 — Hardening + ship | 2026-08-12 | `dd260f2` | `reports/phase-6/REPORT.md` | D6.1–D6.10 |

**`BUILD/DECISIONS.md` is newest-first and mixes heading levels** — most entries are `### DN.M`,
but D5.8 onward and all of D6 are `## DN.M`. A grep pinned to one level silently reports zero;
use `grep -oE "\bD6\.[0-9]+"` and never conclude a decision record is missing from one heading
pattern. (Cost this session two wrong reads before a prune that depended on the answer.)

Phase 6 task detail (P6.0–P6.12) is pruned per MISSION §8b — see `reports/phase-6/REPORT.md`,
`reports/phase-6/visual-qa.md`, `reports/phase-6/fresh-clone.md`, `reports/phase-6/load-sanity.md`,
D6.1–D6.10, or this file's git history (`git log -p BUILD/STATE.md`).

### Carried backlog from Phase 1 — CLOSED 2026-08-12 (D6.11)
- [x] done — (D1.9) **Won't-do, with a measured reason.** `DbHistoryStore` cannot store what the
      CLI stores: `parse_user_id` (`lemely/db/history_repo.py:128`) raises on any non-UUID id and
      the `users` FK is enforced, while the CLI's `--student-id` is a free-form label (its own
      tests pass `alice`, `bob`, `test_student`). "Migrate" therefore means *the CLI grows a hard
      Postgres dependency*, not a backend swap. A third consumer D1.9 never named:
      `tests/test_web_teacher.py` uses the JSON store as the in-process double for
      `HistoryStoreProtocol`. The product surface is already 100% on Postgres
      (`lemely/web/deps.py:83`), parity is proven (`tests/test_history_repo_parity.py`), and the
      protocol isolates callers — two stores behind one protocol is the right end state, not debt.
      **The build now has zero open checklist items.**

### Honest limitations
**They live in `DELIVERY.md` §5** (148 lines, six subsections: marking accuracy, content corpus,
notifications/scheduling, deliberately-absent items, frontend/measurement, operational), with
each phase's full text in its own report §7. They are **not** duplicated here any more — a
hand-copied mirror of a fact that nothing regenerates is this build's single most repeated bug.
The two worth knowing before touching anything:
- **Marking accuracy misses its gate**: 83.8% mark agreement vs the ≥95% target (D2.5), and
  D3.21's paper 22 was **confidently wrong** — 40/40 marks at confidence 1.0, zero review flags,
  3 marks of pure vision/transcription error.
- **`npx impeccable detect` is vacuous on this machine** (D6.9). It returns `[]` even for files
  written to trip it. A green `impeccable-detect` gate is evidence of nothing.

---

## Operational rules this build paid many sessions for — do not re-derive

- **"Clean tree" is not "pushed."** The resume protocol checks `git status --short` for leftovers,
  which is empty whether or not the remote has your commits. Session 110 found `develop` **3
  commits ahead of origin** — so PR #3, the artifact Habeeby actually reads, had been rendering a
  pruned-away 1012-line STATE.md and an already-corrected report for three sessions. **Use
  `git status -sb` and read the ahead/behind count** at every session start.
- **A `FAIL` line in `check.sh`'s log is NOT the end of the run.** The script does not abort on
  a failed gate. Decide liveness from `ps` and the absence of the `EXIT=` line, never from a
  gate verdict.
- **An 84-byte log stuck after the four backend gates is the NORMAL shape of a healthy run
  mid-`pytest`, not a stall.** `check.sh` prints nothing for a passing gate. Four consecutive
  sessions each read that byte count as a crash. `pgrep -af bin/pytest` before diagnosing.
- **`check.sh`'s log holds a verdict and nothing else** — no test count, no coverage figure.
  Any number quoted anywhere must come from an artifact that actually holds it.
- **While a gate run is in flight, touch no code.** Editing `lemely/` or `web/` mid-run makes
  the verdict a statement about a tree that no longer exists, and nothing in the log shows it.
- **Commit the screenshot corpus only after `EXIT=0`, and never wip-commit a dirty `reports/`
  while a run is in flight.** A crashed audit leaves a *partial* corpus, and the resume
  protocol's "clean up a dirty tree with a wip commit" would freeze that mid-run snapshot as
  if it were a curated baseline.
- **A gate verdict is a statement about a tree.** Prove it applies to HEAD with
  `git diff <run-tree>..HEAD -- lemely web scripts tests Makefile pyproject.toml` before
  quoting it. P6.6's `EXIT=0` was true of a tree HEAD had already moved past.
- **"Executable not found" is an environment answer, never a verdict on the code.** Hit three
  times on three different binaries (`mypy`/`lint-imports` under pre-commit, `supabase` in a
  non-interactive shell, `mypy` in the CI pre-commit job). The third nearly became a verdict
  about *Docker containers*, one level further from the missing binary, which is why it
  convinced.
- **A test asserting a concurrency guarantee must be shown to fail *repeatedly* when that
  guarantee is removed — count, don't eyeball** (P6.2). One of this build's own concurrency
  tests passed with the lock it claimed to verify removed (4 unsynchronised threads rarely
  overlap: 8 pass / 12 fail over 20 runs; with a `Barrier` and 11 threads, 0 pass / 10 fail).
- **A hermetic test of an entry point tests everything except that it is an entry point.**
  12 green tests, then `make seed` died on the live stack. Verify an entry point by running
  it, and on a clean slate.
- **Never run a read-only `reviewer` subagent against the same checkout as an in-flight
  inversion.** It read `deps.py` with the auth guard deliberately off and filed a Critical.
- **An unpinned gate tool is a gate whose verdict changes without a commit.** Every gate tool
  is now upper-bounded on purpose (`ruff==0.15.20` in lockstep with the pre-commit rev,
  `gradio<6.20`, `pytest<10`, `pytest-cov<8`, `mypy>=2.1,<2.2`, `pre-commit<5`,
  `import-linter<3`). Raising one is a deliberate commit that re-runs the gates; that is the
  point. Same shape as P6.6's dated VAPID assertion — **a red that arrives on a calendar, not
  on a change**, invisible to per-commit CI and exactly what a phase-end full run is for.
- **Check whether a fix-it PR predates the failure before treating it as a reason to leave a
  gate red.** PR #4 is named for this CI red but predates it (RUF036 shipped with ruff 0.16,
  days later), so it could never have fixed it, and two of its four changes would hurt: it
  narrows the format gate to `lemely tests` (dropping `web/` and `scripts/`) and uses
  `if: matrix.python-version == "3.13"`, which GHA cannot parse (expressions need
  single-quoted strings).
- **Do not "just upgrade ruff" without budgeting for format churn:** `uvx ruff@0.16.2 format
  --check .` reports 6 files reformatted and the file set widening 340 → 387. The lint side is
  clean, so that upgrade is now a formatting decision on its own, not a blocked one.

## Environment facts worth not re-deriving (cost real work to find)
- **`pre-commit` needs `.venv/bin` on `PATH`, or two hooks fail for the wrong reason.**
  CLAUDE.md mandates `pre-commit run --all-files` before every commit. A bare
  `pre-commit` is **not on PATH at all** (use `.venv/bin/pre-commit`), and running it that
  way still fails `mypy` and `import-linter` with **`Executable 'mypy' not found` /
  `Executable 'lint-imports' not found`** — both are `language: system` hooks that resolve
  their binary off `PATH`, and invoking the venv's pre-commit by absolute path does not put
  the venv's `bin` there. Run it as
  `PATH="/home/sico/Lemely/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files`
  (or `source .venv/bin/activate` first) and all ten hooks pass.
- **A gate run must be launched with `setsid`, or it dies with the session.** Five sessions
  produced five `/tmp/check_p58*.log` files of exactly 84 bytes, each stopping mid-`pytest`.
  It was neither bad luck nor the 600 s foreground Bash cap (the logs are stamped 2–5 minutes
  apart, and a background task died identically — **check the timestamps before accepting a
  duration-based explanation**). The agent *session* dies (resource pressure; 7.8 GB RAM,
  already deep in swap, `pytest` with coverage over 3500 tests is the heaviest thing in the
  run) and takes its whole process group with it. So:
  `setsid nohup bash -c './scripts/check.sh > /tmp/LOG 2>&1; echo "EXIT=$?" >> /tmp/LOG' </dev/null >/dev/null 2>&1 & disown`
  Then poll the log; a session that dies mid-run costs nothing. A full run is ~25 minutes
  (pytest ~10, the audit leg ~11). `check.sh` exports `$HOME/.local/bin` onto PATH itself
  (`scripts/check.sh:34`), which is why it is the entry point — all 13 gates run.
- **A dead session leaves an ORPHANED `pytest` behind**, re-parented to PID 1, and the next
  session's `check.sh` then runs concurrently with it — springing the coverage trap below
  without anyone starting a second run deliberately. **Before starting any gate run,
  `pgrep -af "check.sh|bin/pytest"` and kill anything with `PPID 1`.** `git status` shows
  nothing, so the resume protocol's clean-tree check does not cover it.
- **Never run `pytest` concurrently with `./scripts/check.sh`.** Both drive `pytest-cov` and
  contend on the same `.coverage` file, so the *coverage figure* comes back badly wrong while
  the run still exits 0 — a concurrent run reported **89.67% with `practice_repo.py` at 68%**
  where a clean serial run of the identical tree reported **90.37% and 99%**. The test counts
  stayed correct both times, which is what makes it convincing. Re-measure serially before
  believing any coverage drop.
- `pytest -q` emits **no `N passed` line** (a reporter plugin eats it). Count the progress
  characters in the `^[.sFEx]+ +\[ NN%\]` lines, or read the `Total coverage:` line.
- **`pytest --collect-only` still runs the coverage plugin** and will clobber `.coverage` —
  pass `--no-cov`. Its `-q` output is one `path: N` line per file, so the total is
  `... | grep -E "^tests/.*: [0-9]+$" | awk -F': ' '{s+=$2} END {print s}'`.
- **`tsc -b` is incremental and a stale `node_modules/.tmp` hides real errors.**
  `web/tsconfig.test.json` was missing `jsx` for a whole phase — every test importing a `.tsx`
  fails TS6142 — and `npm run build` reported success anyway because the tsbuildinfo predated
  the test. **`rm -rf web/node_modules/.tmp` before believing a green build.** A bare
  `npx tsc --noEmit -p tsconfig.json` is NOT the web typecheck; `tsc -b` covers a larger
  project set and is the stricter gate.
- **`cd` in one Bash call persists into the next.** A `cd web` for an npx run leaves the
  following command running from `web/`, where `.venv/` and `.pre-commit-config.yaml` do not
  exist — which reads as "the venv is gone". Prefix with an absolute `cd /home/sico/Lemely`.
- `GEMINI_API_KEY` lives in `/home/sico/Lemely/.env` and is **not** exported into a
  non-interactive shell — `set -a && . ./.env && set +a`.
- The UI gates write to gitignored `reports/.scratch` (D3.2). Re-baseline explicitly with
  `LEMELY_REPORT_DIR`; never commit into a previous phase's report dir.
- The E2E backend is `scripts/e2e_server.py` on port 8000 — there is no module-level `app`
  attribute on `lemely.web.app`.
- `scripts/seed_e2e.py` is the ONE seeding path for both harnesses, all 5 roles.
  `lemely/db/seed.py` is the *demo-account* path (`make seed`): `<role>@demo.lemely.local` /
  `Demo-Lemely-1!`, parent by phone `+10000000000`. **A demo-data cleanup filter must be
  anchored to the `DEMO_ACCOUNTS`/`DEMO_PARENT` constants, never to a domain suffix another
  seeder also uses** — matching `%parents.lemely.local` once deleted 206 rows instead of 5.
- **The screenshot corpus has THREE producers and running one silently drops the others.**
  The audit runner covers 43 screen ids; `web/e2e/screenshots.spec.ts` owns
  S-06/S-10/S-14/S-15/S-17 and `web/e2e/correct-paper.spec.ts` owns the two `p2.10-*`
  captures. `TOKENSAVE_DISABLE_GREP_HOOK=1 grep -ln "SCREENS_DIR" web/e2e/*.ts` names every
  producer in one line; run it before believing any `removed` count.
- **`compare_screens.mjs --json` takes a REPO-relative path and rejects `../`** even when your
  cwd is `web/`. It fails *after* printing the whole comparison, so the lists scroll past and
  it looks like a successful run that wrote nothing.
- **The visual compare can never be pixel-clean**: `scripts/seed_e2e.py`'s `run_tag` is random
  per run, so every screen rendering a class name changes on every re-baseline. Read
  **`removed`** (must be 0), not `changed`, as the regression signal.
- **The past-paper corpus is outside this repo**: `/home/sico/PaperScraper/papers/CAIE/igcse/
  <subject>-<code>/<year>/<session>/` (648 PDFs, 0580/0606/0625). `Sources/` holds only mark
  schemes and the 4 solved scripts — no question papers. Read-only from here.
- Re-parse mark schemes with `lemely parse-mark-schemes <corpus-dir> --output-root
  outputs/schemes --force --on-error continue` (~54s for 0625; 32/72 parse).
- **The ntfy server has attachments DISABLED — do not keep retrying them.** MISSION §7 says to
  PUT a file with a `Filename:` header; that endpoint returns **HTTP 400 `{"code":40014,
  "error":"invalid request: attachments not allowed"}`** on this instance (server-side config).
  The JSON publish endpoint itself works fine (200). Put the substance **in the message body**
  and use `click`/`actions` to link the artifact on GitHub instead.
- **`ruff` excludes `lemely/db/migrations/versions` via `extend-exclude`** (pyproject), and
  **naming a migration file explicitly on the ruff command line overrides that exclusion** —
  so `ruff check lemely/db/migrations/versions/00NN_x.py` reports TC003 on the standard
  `from collections.abc import Sequence` header that *every* migration has and that
  `./scripts/check.sh` correctly ignores. Lint migrations only through `check.sh`.
- **The backend cannot run more than one replica** (D6.6). `JobRegistry`
  (`lemely/web/jobs.py:31-37`) and the parent OTP challenge store
  (`lemely/auth/service.py:107`) are process-local. Two replicas ⇒ a student reconnects to a
  replica that never heard of their job, and a parent's OTP is issued on one instance and
  verified on another. Caught by no test in this build.
- **The $8 Gemini ledger lives on the ephemeral container filesystem** (`/app/.lemely-cache`),
  so a host that recycles containers resets measured spend to zero while the real bill climbs.
  Mount a volume or the hard cap stops being a cap.

## Session journal
See `BUILD/JOURNAL.md` for the dated 3–6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x–D6.x). Superseded per-task narrative for every phase has been
pruned from this file per MISSION §8b now that the reports are committed — see the git
history of this file, or the phase `REPORT.md` files, if the detail is ever needed again.
