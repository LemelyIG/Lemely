# Phase 6 — Hardening + Ship — Milestone Report

**Branch:** `feature/phase-6-hardening` (off `develop` at `76450ff`)
**Dates:** 2026-08-11 → 2026-08-12 (sessions 94–105)
**Commits:** 42 on the branch
**Gemini spend:** `$0.19641 / $8.00` cumulative — **Phase 6 itself spent `$0.00000`.** Nothing
in a hardening phase calls a model, and every automated test mocks Gemini (D4.3 made that
structural). Source of record is the ledger `outputs/gemini_spend.json`, not this line.

Every number in this report comes from a committed artifact that holds it, named inline. Where
a figure could not be derived from an artifact, it is absent rather than estimated — that
discipline is the direct product of §6.3 of `DELIVERY.md` and of the drifts this build has
already paid for (see §8).

---

## 1. What was built (task → outcome)

| Task | Outcome | Commits |
|---|---|---|
| **P6.0** Reconnaissance + phase plan | Established from disk that Docker Compose, Dockerfiles, deployment docs and `DELIVERY.md` were **entirely unbuilt** — Phase 6 built them from zero rather than hardening something existing. `node -v` 26.6.0, so `impeccable detect` was runnable. | `5c36a93` |
| **P6.1** Gate-affecting hardening | Both carried gate limitations **closed**. `web/e2e/` typechecked for the first time (D3.20 → D6.1); Lighthouse performance floor made a real gate and the routes fixed rather than the bar lowered (D4.25 → D6.2). Entry chunk **1.3 MB → 397 kB across 90 chunks** via `React.lazy` per portal. | `3eb0c5e`, `23a5261`, `148f34e` |
| **P6.2** Concurrency + load sanity | `tests/test_concurrency.py` (3 tests, real thread pools) + `scripts/load_sanity.py`. **Found a real race:** `XpService.award`'s daily anti-farming cap was a read-then-write with no lock — 8 concurrent awards against a cap of 3 all succeeded. Fixed with `with_for_update=True`. | `1cad838` |
| **P6.3** Security re-review | The authz matrix is now **generated, not hand-listed** — it derives the route set from the app and asserts equality, so an undeclared route fails. **121 route operations, nothing unguarded.** 573 new test cases. No production code changed. | `b8913cb`, `7e3e012` |
| **P6.4** Docker Compose | `Dockerfile`, `web/Dockerfile`, `web/nginx.conf`, `docker-compose.yml`, `docker-entrypoint.sh`, `scripts/up.sh` behind **`make up`** as the single command. Backend joins Supabase's own `supabase_network_Lemely` as an `external` network. No CORS middleware — deliberately (same-origin via nginx). | `e81f2f9` |
| **P6.5** Deployment docs | `docs/deployment.md`: the working local stack, a Supabase-Cloud recipe, the configuration reference, a copy-paste checklist. The cloud half **has never been executed and the document opens by saying so.** Writing it found two facts nothing had stated (§7). | `882f983` |
| **P6.6** Full-suite pass | **`EXIT=0`, all 13 gates PASS, 0 skipped** — the first fully green full-suite run of the build. The one failure it found was a **time bomb, not a flake** (D6.7, §8). | `6005b20` |
| **P6.7** Full-product visual QA sweep | `AUDIT_EXIT=0`, `check_ui_gates.py` EXIT=0, **`removed: 0` against both baselines.** Every route now ≥80 Lighthouse performance. Fixed a live CLS defect on `student-standings`. Built per-role contact sheets, which did not exist. | `46bd5f7`, `1ea5de9` |
| **P6.8** README + CHANGELOG + version | Both rewritten for the shipped product; version **1.0.0** in `pyproject.toml` and `web/package.json`; `lemely/web/app.py` imports `__version__` instead of hand-copying it. | `12dff56`, `2bee4cb`, `818e269`, `33270b4`, `7e5a999` |
| **P6.9** `DELIVERY.md` | The comprehensive final document. §6 Evidence built as three tables: each measured number paired with the command that re-derives it; the Phase-5 baseline recomputed from committed JSON; run-dependent figures left **deliberately blank** with the task that fills each. | `ed0f6b7`, `af87de7`, `2b0e506` |
| **P6.10** Fresh-clone acceptance | **Run for real and passed.** A clone into `/tmp/lemely-fresh-1`, the documented commands executed verbatim. `make up` EXIT=0, all five roles authenticate **through nginx**. Found four defects invisible to all 13 gates (D6.8). Required making `lemely/db/seed.py` real first — it had been stubs with a bare `pass`. | `b5bc7c7`, `e2ed097`, `310fade`, `fe8f514` |
| **P6.10-followup** | The container emitted **no `lemely.*` record below WARNING at all** — `python -m lemely.web` never called `configure_logging()` and uvicorn's `LOGGING_CONFIG` carries no `root` entry. Fixed and pinned by `tests/test_web_entrypoint.py`, inverted per the P6.2 rule. | `66950f3` |
| **P6.11** This report, merge, PR, ntfy | — | this commit |

---

## 2. Acceptance criteria (MISSION §4, Phase 6)

| Criterion | Status | Evidence |
|---|---|---|
| Full-suite pass: backend, frontend, E2E across all roles on seeded data | **PASS** | §3, §4 |
| Concurrency test (parallel uploads/markings) | **PASS** | `tests/test_concurrency.py`, 3 tests, each inverted and counted |
| Basic load sanity on the API | **PASS** | `reports/phase-6/load-sanity.{json,md}` — 8 endpoints, concurrency 10, **10,251 requests, 0 errors** |
| Security re-review (authz matrix re-verified) | **PASS** | `tests/test_authz_matrix_complete.py` — 121 route operations, 5 public / 12 role-agnostic / 104 role-gated, nothing unguarded |
| Docker Compose: one command, correct CORS/proxy, documented | **PASS** | `make up`; verified on a real stack and again from a fresh clone |
| Deployment docs for future free-tier cloud | **PASS, with a stated limit** | `docs/deployment.md` — the cloud half is unexecuted and says so on line one |
| Full-product visual QA sweep; regression vs Phase-2.5 is a blocker | **PASS** | §5 — `removed: 0` against both the Phase-2.5 and Phase-5 baselines |
| `DELIVERY.md` | **PASS** | `DELIVERY.md`, all sections closed |
| README, CHANGELOG, version bump | **PASS** | `1.0.0` in both manifests |
| Fresh-clone test → working product, 5 demo roles | **PASS** | `reports/phase-6/fresh-clone.md` |

---

## 3. Test & coverage summary

<!-- P6.11-FILL: figures below come from the P6.11 full-suite run, /tmp/check_p611.log -->

---

## 4. Quality gates (MISSION §6)

The figure of record for this phase is the **P6.11 run on the final tree**, not P6.6's. P6.6
ended `EXIT=0` on `6005b20`, but three commits landed after it and one of them (`7e5a999`)
touched real code — so that verdict was true about `6005b20` and not about HEAD. This is the
re-run.

<!-- P6.11-FILL: 13-gate table -->

**One gate must be reported as vacuous rather than counted as a pass.** `npx impeccable detect`
(impeccable 3.5.0) returns `[]` for `src/` **and for files deliberately written to trip it** — an
inline `style={{color:"#ff0000"}}`, an off-scale `font-size: 13.7px`, an em-dash-overuse file —
with `--json`, `--quiet` and `--no-config` alike, exit 0 and zero bytes every time. No
`.impeccable` config suppresses anything. So MISSION §4's "resolve every finding" is satisfied
trivially and **a green `impeccable-detect` gate is evidence of nothing.** Not chased: it is
third-party tooling, the deterministic checks that do bite (axe, Lighthouse, console-error,
horizontal-scroll) are unaffected, and the `/impeccable audit` skill pass is a separate,
non-vacuous leg (`reports/phase-6/impeccable-audit.md`, 15/20, Good).

---

## 5. Visual + accessibility evidence

All figures recounted from the committed JSON for this report, not copied from the audit log.

| Measure | Phase 5 | **Phase 6** | Source |
|---|---|---|---|
| axe route-states | 73 | **73** | `reports/phase-6/axe/_summary.json` |
| axe violations (critical/serious/moderate/minor) | 0/0/0/0 | **0/0/0/0** | recounted over all 74 files |
| Lighthouse route reports | 44 | **44** | `reports/phase-6/lighthouse/` (45 files; `_summary.json` is a list, not a route) |
| Lighthouse a11y floor | 96 (`teacher-review`) | **96 (`teacher-review`)** | recounted |
| Lighthouse routes below a11y 95 | 0 | **0** | recounted |
| Lighthouse **performance** floor | 65 (`teacher-quiz-detail`) | **80 (`teacher-quiz-detail`)** | recounted |
| Lighthouse routes below performance 80 | **8** | **0** | recounted |
| Console errors | 0 | **0** | `console-errors.json` |
| Horizontal-scroll violations | 0 | **0** | `responsive-summary.json` |
| Screens / screenshots | 43 / 246 | **48 / 246** | `reports/phase-6/screens/` (48 directories; a `find -maxdepth 1 -type d \| wc -l` counts the parent and reads as 49) |

**The headline is the performance column.** Phase 5 shipped with eight routes below the MISSION
§11 floor and a green `ui-thresholds`, because the check did not exist (D4.25). Phase 6 built
the check *and* passed it — every route in the product is now ≥80, with the floor sitting exactly
on the bar.

**Cross-phase compare — `removed: 0` against both baselines, which is the gate.**

| Baseline | added | **removed** | changed | unchanged |
|---|---:|---:|---:|---:|
| `reports/phase-2.5/screens` (39 files) | 207 | **0** | 39 | 0 |
| `reports/phase-5/screens` (246 files) | 0 | **0** | 112 | 134 |

`changed` is not a regression signal in this build and never can be: `scripts/seed_e2e.py` mints
a random `run_tag` per run, so every screen rendering a class name differs on every re-baseline.
`removed` is the number MISSION §4 defines a blocker by, and it is zero.

**Contact sheets:** `contact-sheet-index.html` → per-role `student` / `teacher` / `parent` /
`shared` / `unclassified`. Per-role sheets did not exist before this phase; `audit.mjs` wrote one
flat sheet. `web/scripts/contact_sheets.mjs` (`npm run contact-sheets`) reads only what is on
disk, so sheets regenerate from a committed corpus without an 11-minute audit run.

---

## 6. The defects this phase found in existing work

A hardening phase is judged by what it catches. Six real defects, none of which any prior gate
had surfaced:

1. **`XpService.award` could be defeated by concurrency** (P6.2). Read-then-write with no lock;
   distinct `dedupe_key`s mean migration 0013's unique constraint cannot save it. **Two failure
   modes from one missing lock** — the cap bypass that motivated the fix, and a
   `uq_streaks_user_id` UniqueViolation the inverted run actually produced. The streak symptom is
   the worse one, because `award_xp_safely` is fail-open: a real student silently loses XP with
   every gate green.
2. **An empty env var is not an unset one** (P6.10, D6.8). `${VAR:-}` in compose made pydantic
   build `SecretStr("")`, so every `is None` "not configured" check answered *configured*.
   `/api/health` reported `apiKeyConfigured: true` on a stack that cannot mark a paper, and
   GoTrue's explicit "key is not configured" AuthError never fired — sending an empty `apikey`
   that local Kong accepts and **Supabase Cloud would reject as an unrelated-looking 401**.
3. **The container logged nothing below WARNING** (P6.10-followup). `python -m lemely.web` never
   called `configure_logging()`; uvicorn's default `LOGGING_CONFIG` carries no `root` entry, so
   records fell through to `logging.lastResort`, pinned at WARNING. Nothing raises, nothing is
   logged about the loss — invisible for five phases.
4. **`lemely/db/seed.py` created nothing** (P6.5 → P6.10). `seed_reference_data` and
   `seed_demo_accounts` were stubs with a bare `pass` that logged a cheerful `db.seed.done`.
   `make seed` inserted zero rows while three documents described the accounts it made.
5. **A test that was decoration** (P6.2). `test_device_cap_holds_under_concurrent_logins`
   *passed* with the lock it claimed to verify removed — 4 unsynchronised threads rarely overlap
   (8 pass / 12 fail over 20 runs). Fixed in the test only (`threading.Barrier`, 11 threads),
   re-measured at **0 pass / 10 fail** with the lock removed.
6. **A time-bomb test** (P6.6, D6.7). `tests/test_push_transport.py:170` signed a VAPID assertion
   at an injected clock and verified it against the **real wall clock**; RFC 8292 caps the
   assertion at 24h, so it was green on the day it was written and red in every run after
   2026-08-11 12:00 UTC. Product code was correct and untouched.

Plus three defects in the fresh-clone path (README's `pip install -e ".[dev,ui]"` omitted the
`db`/`web` extras, so `make db-migrate` and `make seed` both failed outright from a clone;
`DEMO_PARENT.display_name` was declared and applied nowhere; `python` is not a command on
Debian-family systems), and one live CLS defect on `student-standings` (P6.7, §5).

**Two rules this phase established, both now standing:**
- **A test asserting a concurrency guarantee must be shown to fail *repeatedly* when that
  guarantee is removed. Count, don't eyeball** — a single inversion run clears nothing.
- **A hermetic test of an entry point tests everything except that it is an entry point.**
  12 green tests, then `make seed` died on the live stack. Verify an entry point by running it,
  on a clean slate.

---

## 7. Known limitations — reported, not resolved

The full carried set from Phases 2–5 is in `DELIVERY.md` §5 and is not duplicated here. Phase 6's
own additions:

- **The backend cannot run more than one replica** (P6.5, D6.6). `JobRegistry`
  (`lemely/web/jobs.py:31-37` — every in-flight correction job and its SSE stream) and the parent
  OTP challenge store (`lemely/auth/service.py:107`) are **process-local**. Two replicas ⇒ a
  student reconnects to a replica that never heard of their job, and a parent's OTP is issued on
  one instance and verified on another. Intermittent, unreproducible, tripped silently by any host
  that autoscales by default, and caught by no test in this build.
- **The $8 Gemini ledger lives on the ephemeral container filesystem** (`/app/.lemely-cache`), so
  a host that recycles containers resets measured spend to zero while the real bill climbs. Mount
  a volume or the hard cap stops being a cap.
- **The entrypoint runs `alembic upgrade head` on every start.** Right for a one-command local
  bring-up, wrong for a production deploy where migration is a separate gated step.
  `docs/deployment.md` says so; the `LEMELY_RUN_MIGRATIONS` guard is *described but not
  implemented*, deliberately — an untested branch in the container start path would risk the
  `make up` P6.4 verified.
- **`/api/teacher/overview` is 10–40× slower than everything else measured** — p50 396 ms / p95
  458 ms against 8–150 ms elsewhere. The shape of an N+1 across a teacher's classes and students.
  Not chased (an observation on seeded data, not a failing test), but it is the first place to
  look if the teacher console feels slow.
- **`npx impeccable detect` is vacuous on this machine** (§4). A green gate there means nothing.
- **The cloud deployment recipe has never been executed.** Local `make up` is verified from a
  fresh clone; the Supabase-Cloud + container-host half of `docs/deployment.md` is reasoned from
  the config surface with every claim anchored to a `file:line`, and is labelled as untested.
- **The fresh-clone run did not exercise a cold `supabase start`** — the stack was already
  running, so `up.sh` took its already-running branch. Stated rather than rounded off.
- **Two frontend gaps left open on purpose, both in `DELIVERY.md`:** the ~600 arbitrary Tailwind
  literals across 41 files (a 600-site rewrite at ship time whose only acceptance signal is a
  compare that cannot be pixel-clean), and the 54 sub-44px `size="sm"` controls (WCAG 2.2 AA met,
  AAA not — the Phase-2.5 §8 gap, re-confirmed rather than rediscovered).
- **Lighthouse runs on `default` states only**; axe runs on all 73 (deliberate, D3.17). **G-10
  declines Lighthouse on purpose** (D5.17) — `runLighthouseAudit` drives its own navigation and
  would score the plain login form under G-10's slug.
- **Seeded demo credentials are published in the README.** Seeding a real deployment therefore
  hands anyone who has read this repo a `platform_admin` login. `docs/deployment.md` §5.3 states
  the consequence.

---

## 8. Decisions recorded this phase

`BUILD/DECISIONS.md` **D6.1–D6.8**:

| ID | Decision |
|---|---|
| D6.1 | `web/e2e/` gets its own tsconfig project, not a seat in the vitest one |
| D6.2 | The Lighthouse performance floor becomes a real gate, scoped exactly as MISSION words it |
| D6.3 | The concurrency pass found a real race in the XP cap, and one of its own tests was decoration |
| D6.4 | The authz matrix becomes generated, and the security sweep found nothing to fix |
| D6.5 | The deployment stack joins Supabase's network, and ships no CORS on purpose |
| D6.6 | Deployment docs written from the config surface, and the two blockers they found |
| D6.7 | The full-suite run found a time-bomb test, not a flake |
| D6.8 | The fresh-clone run found four defects, and the product one was a claim with nothing behind it |

**The recurring bug of this build, named once here because it appeared four separate times:** a
hand-written mirror of a fact that nothing regenerates. `gemini_spend_usd` in STATE drifted from
the real ledger; the `SeedContract` drifted; `app.py` hand-copied a version string; three
documents described demo accounts a stub never created; and STATE carried "30 Playwright tests"
for a whole phase against a real 34. Every one was caught by *re-deriving from the artifact*
rather than reading the mirror. That is why `DELIVERY.md` §6 pairs each number with the command
that re-derives it, and why this report names a source per row.

---

## 9. Blockers

None open. `BUILD/BLOCKERS.md` B1/B2/B3 were all raised and resolved in Phase 3.

---

## Appendix — files of record

| Artifact | What it holds |
|---|---|
| `DELIVERY.md` | The comprehensive final document — feature inventory, evidence, limitations |
| `docs/deployment.md` | Local stack + untested cloud recipe + configuration reference |
| `reports/phase-6/fresh-clone.md` | The fresh-clone acceptance run, verbatim commands and outputs |
| `reports/phase-6/visual-qa.md` | The visual QA sweep, its three corpus producers, and the CLS fix |
| `reports/phase-6/impeccable-audit.md` | The `/impeccable audit` skill pass (15/20, Good) |
| `reports/phase-6/load-sanity.{json,md}` | 8 endpoints, concurrency 10, 10,251 requests, 0 errors |
| `reports/phase-6/axe/`, `lighthouse/` | Per-route JSON behind every figure in §5 |
| `reports/phase-6/screens/` | 48 screens, 246 screenshots |
| `reports/phase-6/contact-sheet-*.html` | Per-role contact sheets + index |
| `reports/phase-6/compare-vs-phase-{2.5,5}.json` | The regression gate: `removed: 0` against both |
