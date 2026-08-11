# Lemely — Delivery Document

**Status of this document:** it is the final record of what this build produced,
what it did not, and what a reader must not assume works. Every figure in it is
measured off committed artifacts rather than carried forward by hand — this
build was burned several times by hand-copied numbers that nothing regenerates,
and §6 says where each number comes from so it can be re-derived.

**The one thing to read if you read nothing else:** §5, *Honest limitations*.
It carries every limitation recorded in Phases 2 through 5, whether or not
Phase 6 fixed it. A feature listed as `Delivered` in §3 may still appear there
with a constraint on what "delivered" means.

---

## 1. What Lemely is

A SaaS platform for IGCSE/O-Level/AS/A-Level students, their parents and their
teachers, scoped for launch in Egypt (English-only UI). A student photographs or
uploads an attempted past paper; Lemely extracts the answers, marks them against
the official marking scheme with method-mark awareness, and returns per-question
marks, a letter and numerical grade, a predicted grade after boundaries,
mistakes, weakness topics and performance trends. Around that core loop sit
student/teacher/parent dashboards, AI content generation, adaptive study plans
and a Duolingo-style engagement layer.

**Board scope for this build:** CAIE only — Mathematics 0580, Additional
Mathematics 0606, Physics 0625. The architecture is board-agnostic; Edexcel and
Oxford AQA would arrive as data plus parser plugins.

**Explicitly out of scope, by decision, not by omission** (MISSION §1 and §9):
payment processing (the subscription/seat data model and plan gating exist;
activation is a manual platform-admin toggle), the igclub calculator, Arabic UI,
a real SMS provider, and live cloud hosting.

## 2. Phase reports

Each phase has its own report with the command outputs, screenshots and test
counts that back it. This document links rather than restates them.

| Phase | Scope | Report |
| --- | --- | --- |
| 0 | Foundation repair | [`reports/phase-0/REPORT.md`](reports/phase-0/REPORT.md) |
| 1 | Database, auth, tenancy | [`reports/phase-1/REPORT.md`](reports/phase-1/REPORT.md) |
| 2 | The core correction loop | [`reports/phase-2/REPORT.md`](reports/phase-2/REPORT.md) |
| 2.5 | Design system + frontend quality foundation | [`reports/phase-2.5/REPORT.md`](reports/phase-2.5/REPORT.md) |
| 3 | Teacher + parent surfaces | [`reports/phase-3/REPORT.md`](reports/phase-3/REPORT.md) |
| 4 | Content generation + study plans | [`reports/phase-4/REPORT.md`](reports/phase-4/REPORT.md) |
| 5 | Engagement layer | [`reports/phase-5/REPORT.md`](reports/phase-5/REPORT.md) |
| 6 | Hardening + ship | [`reports/phase-6/REPORT.md`](reports/phase-6/REPORT.md) |

Design and product truth live in [`docs/LEMELY_UI_SPEC.md`](docs/LEMELY_UI_SPEC.md),
[`DESIGN.md`](DESIGN.md) and [`PRODUCT.md`](PRODUCT.md); decisions in
[`BUILD/DECISIONS.md`](BUILD/DECISIONS.md); deployment in
[`docs/deployment.md`](docs/deployment.md).

## 3. Feature inventory

Every item in MISSION §9's inventory appears below exactly once, with the files
that implement it and the tests that prove it. `Delivered (limited)` means the
feature works but with a stated constraint — the constraint is in the feature
cell, and the fuller version is in §5.

<!-- FEATURE-TABLE -->

## 4. Deferred, and why

These were named as out of scope at the start of the build and were not built.
They are listed so that "absent" is never mistaken for "missed".

| Deferred | Why |
| --- | --- |
| Payments (Paymob / Fawry) | Out of scope by MISSION §1. The subscription and seat data model exists and plan gating is enforced; account activation is a manual platform-admin toggle. |
| igclub calculator | Out of scope for v1. |
| Edexcel / Oxford AQA | Architecture is board-agnostic; these arrive as data plus parser plugins, not as a rewrite. |
| Arabic UI | v1 is English-only. |
| Real SMS provider | Parent phone-OTP ships behind a provider abstraction with a mock provider that logs the OTP. One config switch changes it. |
| Cloud hosting | The definition of done was a one-command local stack plus written deployment docs. No live hosting was in scope. |

## 5. Honest limitations

Carried forward in full from every phase, whether or not a later phase fixed
them. Struck-through entries were closed and are kept so the record stays
readable rather than quietly rewritten.

### 5.1 Marking accuracy — the most important limitation in this document

- **The synthetic accuracy gate is NOT met (D2.5).** Mark-level agreement is
  **83.8% against a ≥95% target**, and flag recall is **27.3%** against a target
  of flagging 100% of disagreements. Threshold tuning (D2.2/D2.3) and
  deterministic calculated-answer verification (D2.4) are both exhausted; the
  remaining gap is free-form algebraic method verification, which is materially
  harder and was never in scope. This number did not move in Phases 3, 4 or 5,
  and this build does not claim examiner-level accuracy.
- **Real past-paper measurement (D3.21), reported separately and never
  averaged:** paper 22 predicted **37 vs 34** actual, paper 41 predicted
  **63 vs 66**. Both landed inside the stated ±10%-of-max tolerance, which was
  fixed before any result was seen.
- **Paper 22 was confidently wrong, and that is the finding worth acting on.**
  All 40 marks came back at confidence 1.0, band high, with zero review flags —
  and it was still 3 marks off. MCQ marking is deterministic string comparison
  against the official key, so no marking-judgement error is possible there:
  every one of those 3 marks is **vision/transcription** error. The confidence
  number is measuring the marker while the mistake happened in the extractor.
  Propagating extraction confidence into per-question confidence on the
  deterministic MCQ path changes the marking contract and was deliberately not
  patched unattended.

### 5.2 Content corpus

- **The question bank could not be filled from mark schemes alone (D3.7),** and
  Phase 4 built the stem extractor that closed it (D4.1/D4.2) — 72 papers into
  273 banked 0625 stems.
- **0580 and 0606 have zero ingested questions.** Placement and practice
  therefore honestly refuse for two of three subjects rather than fabricating
  content. The ceiling is **mark-scheme parse coverage (32/72 for 0625)**, not
  stem extraction — that is the highest-leverage thing to improve next.
- **A practice set is marked but its result cannot be read.** Marking runs and
  the marks are in the database; no route exposes them for `kind=practice`.
  Only the read is missing.

### 5.3 Notifications, scheduling and push

- **No scheduler exists in this build (D5.9).** `streak_warning` and
  `study_plan_reminder` are service methods that nothing invokes on a timer, and
  **at-risk rule 3 (≥14 days inactive) cannot fire at its seam** — the alert
  fires on correction, and a student who just uploaded is by definition active.
  These are not delivered notification types.
- **No VAPID keys exist on the build machine,** so the push transport is
  unavailable by design and no real push can be delivered in any harness here.
  What is assertable is the notification inbox row and G-12's unavailable state.
- **Push is payload-less (D5.10),** so an offline arrival renders a generic
  "You have a new notification" — browsers require some notification per push.

### 5.4 Deliberately absent, because the honest source does not exist

Each of these ships as an explicit empty or unavailable state rather than as
invented data (UI spec §1.4, *never invent precision*):

- Exam-calendar dates — no CAIE timetable on this machine, and no CLI wrapper
  around `ExamCalendarService.ingest`.
- S-31 lifetime stats — a count of `xp_events` is wrong by construction: caps
  write no row, and dedupe writes one row for two markings.
- S-29 avatar image — no avatar storage; a monogram ships instead.
- G-10 rough location — no geo-IP and no stored IP.
- G-12's `weekly_summary` toggle — no backend enum value for it.

**None of these is a gap to be "filled" later without first building the
source.**

### 5.5 Frontend, accessibility and measurement

- ~~**`web/e2e/` and `playwright.config.ts` are in no tsconfig `include`
  (D3.20)**~~ — **CLOSED in Phase 6 (D6.1)**. The most expensive gate is now
  typechecked for the first time, via a separate `web/tsconfig.e2e.json`
  project.
- ~~**The Lighthouse performance floor is not enforced (D4.25)**~~ — **CLOSED in
  Phase 6 (D6.2)**, and the routes were fixed rather than the bar lowered: a
  single 1.3 MB bundle serving all 44 routes was split into 90 lazy chunks
  (entry 397 kB), taking the student-route performance minimum from 70 to 89.
- **Teacher routes are deliberately not performance-gated.** MISSION §11 states
  a floor for student routes only; inventing one for the others at the moment it
  would fail would be a scope change, not diligence.
- **Lighthouse runs on `default` states only** (deliberate, D3.17); axe runs on
  every audited state.
- **G-10 declines Lighthouse on purpose** — the Lighthouse runner drives its own
  navigation and would score the plain login form under G-10's slug, i.e.
  measure a state it never reached. `/login` is scored on its own entry.
- **The visual comparison can never be pixel-clean.** The E2E seed's `run_tag`
  is random per run, so every screen rendering a class name changes on every
  re-baseline. **`removed` (which must be 0) carries the regression gate; a
  nonzero `changed` count is not by itself a signal.**
- **PWA Lighthouse and camera capture were never live-tested** (no Chromium and
  no camera in the build sandbox, P2.9) — verified by inspection and manual
  trace only. See `reports/phase-2/pwa-limitations.md`. A real-device pass is
  needed before claiming a hard pass.
- **Component-library gaps deferred at Phase 2.5** (report §8): a sub-44px touch
  target, non-heading empty/error tags, no mobile BottomNav, raw `max-[1180px]:`
  literals outside the retrofitted screens, and a momentum-chart/TrendSparkline
  duplication blocked on a DTO change.

### 5.6 Operational

- **The backend cannot run more than one replica (D6.6).** `JobRegistry`
  (`lemely/web/jobs.py`) — every in-flight correction job and its SSE stream —
  and the parent OTP challenge store (`lemely/auth/service.py`) are
  **process-local**. Two replicas mean a student reconnects to a replica that
  never heard of their job, and a parent's OTP is issued on one instance and
  verified on another. Intermittent, unreproducible, tripped silently by any
  host that autoscales by default, and caught by no test in this build.
- **The container entrypoint runs `alembic upgrade head` on every start.** Right
  for a one-command local bring-up, wrong for production, where migration must
  be a separate gated step. `docs/deployment.md` says so.
- **The $8 Gemini ledger lives on the container filesystem** under
  `/app/.lemely-cache`. A host that recycles containers resets measured spend to
  zero while the real bill climbs — mount a volume or the hard cap stops being
  a cap.
- **`/api/teacher/overview` is 10–40× slower than everything else measured**
  (p50 396 ms / p95 458 ms against 8–150 ms elsewhere) — the shape of an N+1
  across a teacher's classes and students. Observed on seeded data during the
  Phase-6 load-sanity pass; not chased, but it is the first place to look if the
  teacher console feels slow.
- **The CLI and Gradio surfaces still use the JSON `HistoryStore`** rather than
  Postgres (D1.9). Parity was proven; the migration was left as opportunistic
  backlog. Gradio is an internal debug tool, not a product surface.
- **No CORS middleware exists, and that is the intended state (D6.5).** nginx
  proxies `/api` to the backend on the same origin the SPA was loaded from, so
  the browser issues no cross-origin request. A split-origin deploy would need a
  config-driven allowlist with `allow_credentials=False`, since auth is
  bearer-token and not cookie-based.

## 6. Evidence

<!-- EVIDENCE -->

## 7. Running it

See [`README.md`](README.md) for local development and
[`docs/deployment.md`](docs/deployment.md) for the containerised stack and the
cloud recipe. The short version:

```bash
make db-up          # supabase start
make db-migrate     # alembic upgrade head
make seed           # reference data + demo accounts
make up             # backend + built SPA, one command
```
