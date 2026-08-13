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
CURRENT PHASE:      3 — IA & UX Flows (Phases 0, 1, 2 DONE)
CURRENT SURFACE:    none (Phase 2 is product-wide foundation)
CURRENT BRANCH:     redesign/phase-0  (off develop; per-phase/surface branches per §11)
NEXT ACTION:        Phase 3 — IA & UX Flows. In order:
                    3.1 Implement the approved IA restructure (D1.1-5, DEFAULTED
                        and therefore approved): drop the student "Elsewhere"
                        nav, add /teacher/review to the sidebar, give students
                        an in-app path to notifications, add a custom 404 and
                        wire the new ErrorBoundary at the route level, and add
                        back/breadcrumb paths in teacher + parent.
                    3.2 First-run flows per role (impeccable shape -> onboard).
                        Empty dashboards become composed "getting started"
                        views, never blank. The EmptyState + marginalia
                        vocabulary for this already exists in the kit.
                    3.3 harden + clarify groundwork: form validation patterns
                        (the kit's Input/Select/Radio already implement inline,
                        near-field errors with visible labels), error copy
                        voice, skeletons instead of spinners (Skeleton exists
                        now), custom 404, skip-to-content link.
                    3.4 RTL-safety rule applies from here to the end: logical
                        properties everywhere, no hardcoded left/right.
                    READ DESIGN.md FIRST. It is the real system now, and the
                    component kit under web/src/components/ui/ implements it.
                    Preview the kit with `npm run preview:kit`.
                    NOTE: build-era screens still consume the compat token
                    aliases in index.css. That is deliberate and documented;
                    Phase 4 migrates them surface by surface.
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
| 2. Brand & Design System | DONE | 2026-08-13 | All 6 steps done. Brand strategy at `BUILD/BRAND.md`; logo hand-authored as SVG after the Gemini refine pass failed on all five named defects (D2 defaulted to ship it). DESIGN.md rewritten from scratch as the Study Notebook; index.css is its implementation with a documented temporary compatibility layer so un-migrated screens pick up the new palette instead of staying Material-3. `tests/test_design_tokens.py` pins every contrast claim and caught two real AA failures plus one greyscale failure in my own draft. Landing-page fabrications C1/C2 fixed, plus a third the audit missed (a stated 0.70 review threshold that is really 0.90). Component kit: 19 components, all 8 states, preview page at `web/dev-previews/` with its own Vite entry so the product can never ship it. Closed the audit's "no skeleton component" and "no error boundary" gaps. Three defects found by verifying rather than trusting the agent reports: RadioGroup did not actually have 8 states; the preview page was silently missing every utility used only inside a component (Tailwind source detection is rooted at the entry CSS, fixed with `@source`, CSS went 28KB→69KB); and a hover-pinning device I built emitted zero CSS and was removed rather than left to quietly pass review. |
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

### Phase 2 deliverables (for later phases to read)

| Artefact | Path | Note |
|---|---|---|
| Design system | `DESIGN.md` | The source of truth. Read before emitting any UI. |
| Brand strategy | `BUILD/BRAND.md` | Meaning, not values. Wins over DESIGN.md on meaning only. |
| Tokens | `web/src/index.css` | Implementation of DESIGN.md, plus a documented temporary compat layer. |
| Contrast guarantees | `tests/test_design_tokens.py` | 28 tests. Pins every ratio DESIGN.md claims. |
| Logo | `web/public/brand/` | mark / mark-mono / mark-favicon. NOT yet wired into `index.html` — that is Phase 6.5. |
| Logo candidates | `BUILD/brand/` | 4 Gemini renders + 1 refine + the D2 contact sheet. |
| Component kit | `web/src/components/ui/` | 19 components, 8 states each. |
| Kit preview | `web/dev-previews/` | `npm run preview:kit`. Separate Vite entry; never shipped. |
| Generation script | `scripts/gen_brand_images.py` | Books spend into the real cost ledger and refuses to breach the ceiling. |

**Budget correction, carried forward:** the mission assumed an $8 Gemini ceiling.
The real one is **$4.99** (`lemely.toml:20`). Image spend this phase was $0.195 of
the $3 allowance; cumulative is **$0.399 / $4.99**.
