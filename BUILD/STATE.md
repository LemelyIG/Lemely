# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 2.5
last_updated: 2026-08-05T13:05:00Z
gemini_spend_usd: 0.0580

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.
- Prune a phase's detail to a single summary line once its `reports/phase-N/REPORT.md`
  is committed and merged to develop (MISSION §8b) — full rationale lives in
  `BUILD/DECISIONS.md` and the phase report, not here.

## Phase 0 — Foundation repair — DONE (2026-07-30)
All 8 tasks complete: CI green (ruff/web), `lemely/io/det/` wired + monolith deleted (D0.5),
persistent Gemini cost ledger ($8 cap, D0.6), HistoryStore corruption surfaced, single lockfile,
`lemely doctor` real reachability. 395 passed / 84.56% cov. Merged to develop.
Report: `reports/phase-0/REPORT.md`. PR #3 (rolling develop→main, NOT merged).

## Phase 1 — Database + Auth + Tenancy — DONE (2026-08-01)
Local Supabase stack, 22-table schema (additive-only, D1.2/D1.3), GoTrue auth + backend-issued
HS256 JWTs (D1.4/D1.5), RBAC on every route + both IDORs killed (D1.6), HistoryStore→Postgres
for the web surface (D1.8/D1.9 — CLI/Gradio kept on JSON store), seat model (D1.10), 3-device
session registry (D1.11). Adversarial review: no Critical/High bypass (D1.12). 548 passed /
85.44% cov. Merged to develop. Report: `reports/phase-1/REPORT.md`.

### Carried backlog from Phase 1 (non-blocking, do opportunistically)
- [ ] todo — (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), then delete
      `lemely/io/history_store.py` + `tests/test_history_store.py`. Parity already proven.
- [ ] todo — (D1.6) Teacher per-tenant ownership (own-classes-only) — lands with the Phase 3
      class model; role boundary is already enforced, row-level ownership is not yet.

## Phase 2 — The core loop, real and end-to-end — DONE (2026-08-05)
Real SSE correction pipeline (P2.1), grade-boundary ingestion from cambridgeinternational.org
(P2.2, D2.1), accuracy harness + 10 golden fixtures across 0580/0606/0625 (P2.3), plagiarism/
AI-detection advisory flags (P2.4), Supabase Storage upload path (P2.5, D2.6), frontend
resurrected from dead code + auth/session foundation (P2.6), student + teacher surfaces wired
to real data (P2.7/P2.8), PWA foundation + camera capture (P2.9), Playwright E2E acceptance
verified against the live Supabase stack with an independent Postgres persistence check
(P2.10). 609 passed / 3 skipped (live-only) / 86.38% cov. Merged to develop (6254879), pushed.
PR #3 updated (title "Phases 0–2", body extended), NOT merged. ntfy sent.
Report: `reports/phase-2/REPORT.md`. Gemini cumulative spend $0.058/$8.00.

### Honest limitations carried forward from Phase 2 (must appear in DELIVERY.md, not silently resolved)
- **Accuracy gate NOT met (D2.5):** mark-level agreement 83.8% vs ≥95% target; flag_recall
  27.3% vs the 100%-disagreements-flagged target. Threshold tuning (D2.2/D2.3) and
  deterministic calculated-answer verification (D2.4) are both exhausted; the remaining gap
  is free-form algebraic method-verification — materially harder, out of scope so far.
- **PWA Lighthouse + camera-capture** not live-tested (no Chromium/camera in this sandbox,
  P2.9) — verified by inspection/manual trace only; see `reports/phase-2/pwa-limitations.md`.
  Needs a real-device/browser pass before claiming a hard pass.

## Phase 2.5 — Design system + frontend quality foundation — NEXT
- [ ] Verify environment: `node -v` ≥ 24 (impeccable detect), `python3 -V`,
      `ls .claude/skills/` shows impeccable, ui-ux-pro-max, design-taste-frontend
- [ ] Confirm DESIGN.md + PRODUCT.md exist and have no unfilled placeholders
      (blocker + high-priority ntfy if not)
- [ ] Read docs/LEMELY_UI_SPEC.md in full; record any conflict with existing
      Phase-2 implementation in DECISIONS.md
- [ ] Build the token source (Tailwind v4 theme + CSS vars) from DESIGN.md
- [ ] Build cross-cutting components with all states + component catalogue
- [ ] Playwright screenshot harness (screen × state × breakpoint, ID convention)
- [ ] Puppeteer audit runner (axe-core, Lighthouse, console errors, captures)
- [ ] Contact-sheet generator; commit baselines
- [ ] Extend scripts/check.sh with the UI gates
- [ ] Retro-fit Phase-2 screens onto tokens + components
- [ ] Impeccable audit → normalize → polish pass on Phase-2 screens
- [ ] Full quality-bar pass; grep proves no stray design values
- [ ] Phase report + contact sheet + PR develop→main + ntfy

Start-of-phase task: expand this into a step-by-step checklist (mirroring how Phase 1→2 were
expanded from the MISSION §4 one-paragraph summary) before dispatching implementation work.

## Phase 3 — Teacher + Parent surfaces
Not yet started. Branch from `develop` as `feature/phase-3-teacher-parent`. Per MISSION §4:
- Teacher: class management, per-class/per-student analytics, aggregate weakness topics,
  at-risk flagging (declining trend OR predicted grade ≥2 boundaries below target OR ≥14
  days inactive — each flag labeled with its reason), human-review queue override-and-annotate
  flow (overrides feed back as recorded corrections; the review-queue *display* already exists
  from P2.8 — this phase adds the override action and at-risk logic on top of it).
- Teacher quiz builder: difficulty targeting by expected grade, included-material selection,
  question pool from generated/classified past-paper questions, assign to class, auto-marked,
  results feed analytics.
- Parent portal: phone-OTP login (the mock-provider auth backend already exists from P1.4 —
  this phase builds the actual portal screens/routes, which don't exist yet), linked children,
  performance + weakness views (read-only), notification preferences.
- This phase is also where teacher per-tenant ownership (own-classes-only, deferred from D1.6)
  should land, since it needs the real class model this phase builds.
- Acceptance: E2E per role; at-risk flags verified against seeded scenarios.


## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
