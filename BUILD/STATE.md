# STATE.md — Lemely Checkpoint File

> This file is the single resume point. On every session start (fresh or after a
> usage-limit reset), read this file FIRST, then `BUILD/STEERING.md`, then continue
> from `NEXT ACTION`. Update this file after every completed work unit, every gate
> result, every DECISION sent or resolved, and every steering message processed.
> Never rewrite history sections; only update the live fields and append to logs.

---

## BUILD (MISSION.md) — COMPLETE

The MISSION.md build is finished. On first redesign session, fill this table from the
actual build outcome (read the prior STATE content / BUILD reports / merged PRs), then
treat it as frozen history.

| Phase | Status | Milestone PR |
|---|---|---|
| (fill from completed build) | DONE | |

Do not reopen build phases. Any build-era bug found during redesign: fix in place
if trivial, otherwise log under REDESIGN → Deferred Issues.

---

## REDESIGN (REDESIGN-MISSION.md) — ACTIVE

### Live status

```
MISSION:            BUILD/REDESIGN-MISSION.md
CURRENT PHASE:      2 — Brand & Design System (Phase 1 DONE)
CURRENT SURFACE:    none (Phase 2 is product-wide foundation)
CURRENT BRANCH:     redesign/phase-0  (off develop; per-phase/surface branches per §11)
NEXT ACTION:        Phase 2 step 6, the LAST open item in this phase: the core
                    component kit and its 8-state preview page under
                    web/dev-previews/. Steps 1-5 are DONE (see the P2 log below).
                    Missing entirely and needed: Input, Select, Radio, Switch,
                    Modal, Popover, Toast, Tabs, Table, Skeleton, Avatar
                    (squircle), Kbd, ProgressBar, Chart wrapper, ErrorState.
                    Already exist and need restyling to the new tokens: button,
                    card, checkbox, chip, slider, stepper, state-views,
                    primitives, plus the product-specific set (confidence-
                    indicator, grade-badge, mark-display, question-row,
                    boundary-bar, paper-identity, processing-state,
                    trend-sparkline, weakness-chip, xp-streak, nav-shells).
                    Read DESIGN.md FIRST — it is now the real system.
                    Then Phase 3 (IA & UX flows), implementing D1.1-5.
LAST UPDATED:       2026-08-13T18:10+03:00
LAST STEERING TS:   1786629365   (poll http://home-server:7532/lemely-ErBPK7TIRGD1sQP5-in/json?poll=1&since=<this>)
                    NOTE: still no inbound message from the human, ever. The only
                    entry on the topic remains my own Phase-0 selftest.
```

### Phase ledger

| Phase | Status | Completed | Notes |
|---|---|---|---|
| 0. Setup & Verification | DONE | 2026-08-13 | All 9 skills loadable; nothing needed installing. Node 26.6.0, Python 3.13.5, Playwright 1.62.1 (web/), Gemini key in gitignored `.env`, spend $0.204/$8 (image budget for this mission ≤$3). impeccable hook already `enabled`; `context.mjs` clean apart from one stale-context finding, fixed. PRODUCT.md already existed from the build era and was corrected rather than regenerated (see notes). ntfy verified in **both** directions. |
| 1. Audit | DONE | 2026-08-13 | Three legs, all read-only, `web/` verified untouched after each. Merged into `BUILD/DESIGN-AUDIT.md`; leg reports in `BUILD/audit/`. 6 critical, 14 major, 3 minor. Root cause is one thing: every token is still the build-era Material-3 palette, so zero pages are Study Notebook yet. Worse than that and independently confirmed by me: 3 fabrications on the landing page, no error boundary anywhere, no skeleton component anywhere. **Coverage is partial and stated so — nothing was verified against a rendered viewport, and 34 of 48 routes were reached by grep only.** |
| 2. Brand & Design System | IN PROGRESS | — | Steps 1–5 done, step 6 (component kit) open. Brand strategy at `BUILD/BRAND.md`; logo hand-authored as SVG after the Gemini refine pass failed on all five named defects (D2 defaulted to ship it). DESIGN.md rewritten from scratch as the Study Notebook; index.css is its implementation with a documented temporary compatibility layer so un-migrated screens pick up the new palette instead of staying Material-3. `tests/test_design_tokens.py` pins every contrast claim and caught two real AA failures plus one greyscale failure in my own draft. Landing-page fabrications C1/C2 fixed, plus a third the audit missed (a stated 0.70 review threshold that is really 0.90). |
| 3. IA & UX Flows | PENDING | — | |
| 4. Surface redesign | PENDING | — | |
| 5. Motion & data-viz | PENDING | — | |
| 6. Hardening & adaptation | PENDING | — | |
| 7. Final QA & report | PENDING | — | |

### Surface ledger (Phase 4 order)

| Surface | Status | Branch | Gates | Merged |
|---|---|---|---|---|
| Student dashboard | QUEUED | — | — | — |
| Past-paper correction flow | QUEUED | — | — | — |
| Study surfaces (classifieds, flashcards, plans) | QUEUED | — | — | — |
| Gamification (XP, streaks, leaderboards) | QUEUED | — | — | — |
| Teacher dashboard + quiz builder | QUEUED | — | — | — |
| Parent views | QUEUED | — | — | — |
| Admin views | QUEUED | — | — | — |
| Auth | QUEUED | — | — | — |
| Marketing / landing | QUEUED | — | — | — |
| 404 / misc | QUEUED | — | — | — |

### Gate status (current surface only)

```
SURFACE:            none
BUILD COMPLETE:     —
INSPECTION ROUND:   —
FINDINGS TO FIX:    —
CONFIRM ROUND:      —
HALLMARK STAMP:     —
HOOK FINDINGS:      —
TESTS:              —
```

### Open DECISIONs

| ID | Question | Options | Default | Sent | Timeout | Status |
|---|---|---|---|---|---|---|
| D1.6 | Build real school-admin + platform-admin screens? None exist; both roles are routed into `/teacher` today. ~7 screens, new route subtree, un-bundles the `TEACHER_ROLES` guard `rbac.spec.ts` asserts against. | A build now / B defer, stay on `/teacher` / C scaffold routes+shells only | **none — deliberately not defaulted** | 2026-08-13T15:05Z | none | OPEN |

D1.6 carries no default on purpose: §10 says a question with no sane default must not be a
timeout question. It does not block Phase 2 or 3. Re-ask before Phase 4 reaches admin views;
if still unanswered then, that is the point to block rather than guess.

### Resolved

| ID | Outcome | When |
|---|---|---|
| D1.1–5 | **DEFAULTED — proceed as proposed.** 60-minute timeout elapsed with no reply. The five cost-free IA corrections are approved by default and are implemented in Phase 3.1. | 2026-08-13T18:10+03:00 |
| D2 | **DEFAULTED — option A, ship the hand-authored SVG mark.** 30-minute timeout elapsed with no reply. Assets are at `web/public/brand/` (mark, mono, favicon cuts). Not yet wired into `index.html`; that is Phase 6.5's strategic-omissions closeout. | 2026-08-13T18:10+03:00 |

### Steering log pointer

Full log: `BUILD/STEERING.md` (created in Phase 0).
Last processed inbound message: none from the human. The only entry on the inbound topic is
my own Phase-0 selftest (`IOd08AgAn9Hf`, ts 1786629363), and `LAST STEERING TS` is set past
it so it can never be replayed as a directive.

### Deferred issues (found during redesign, not blocking)

- **Phase 0 note — PRODUCT.md was corrected, not regenerated.** `/impeccable init` would have
  overwritten a build-era file that already carries five roles, the real product loop, the
  binding anti-references, and the evidence-on-hand list. Four edits were made instead:
  the deprecated `## Register` section became `## Modes` (impeccable v4 dropped register for
  the four visitor modes; nothing reads `## Register` any more), §4's anti-references and the
  protected notebook quality were added, and the line "layouts need not solve RTL yet" was
  replaced — it directly contradicted Phase 3.4's RTL-safety rule.
- **`DESIGN.md` at the repo root is build-era and predates the Study Notebook direction.**
  Phase 2 replaces it. Until then no surface work should read it as the token source.

---

## Update rules (for the agent)

1. Update `Live status` block on every work-unit boundary; `LAST UPDATED` always current.
2. Phase/surface ledgers: flip status only, append notes; never delete rows.
3. Gate status block is scratch space for the current surface; reset it when a surface
   merges (copy its outcome into the surface ledger first).
4. DECISIONs: add on send, move to Resolved with the answer on resolution or timeout
   (mark timeouts as "DEFAULTED").
5. `LAST STEERING TS` advances only after the message is logged AND acted on or queued.
6. Commit STATE.md with the work it describes, same commit.
