# DESIGN-AUDIT.md — Lemely redesign, Phase 1

Merged output of the three Phase-1 audit legs required by `BUILD/REDESIGN-MISSION.md` §5.
Each leg ran read-only in its own subagent and wrote a full report; this file consolidates
them into one ranked punch list and the IA proposal that goes to the human as DECISION D1.

| Leg | Skill | Report | Findings |
|---|---|---|---|
| 1 | `redesign-existing-projects` Diagnose + IA map | `BUILD/audit/diagnose.md`, `BUILD/audit/ia.md` | stack inventory, strategic omissions, 6 IA proposals |
| 2 | `hallmark` slop-gate sweep | `BUILD/audit/hallmark.md` | 5 critical, 6 major, 3 minor |
| 3 | `impeccable` audit + critique | `BUILD/audit/impeccable.md` | per-surface scores, missing-states matrix |

**Nothing under `web/` was modified by any leg.** Verified with `git status --short web/`
after each returned, not asserted.

---

## 1. Verdict

**This is a design-system replacement, not a rescue.** All three legs independently reached
the same conclusion from different angles: the engineering underneath is in good shape, and
the design layer on top is the wrong system.

What is genuinely good, and should be protected rather than rebuilt: a single icon library
(`@phosphor-icons/react`, already what §3.2 mandates), Tailwind v4 already adopted with a
CSS-first config, no fake browser or phone chrome anywhere, no `transition-all`, all three
loaded font faces actually consumed, a documented token-provenance comment block in
`index.css`, and `impeccable detect.mjs` returning **zero findings** across all of `web/src`.
The button and card primitives already lean flat-hairline-and-solid-ink, which is the
direction §4 wants. A codebase that has to be argued out of gradients and glassmorphism
would be a much worse starting point than this one.

What is wrong is nearly all one root cause with many symptoms: **every token traces to the
build-era Material-3 "Academic Warmth" palette** (terracotta `#964232` / teal `#006857` on
`#fff8f6`), so **zero pages reflect the mandated Study Notebook identity.** There is no
notebook texture, no marginalia, no handwritten accent face, and the logo is a placeholder
lowercase italic *l* in a filled circle. This is expected pre-Phase-2 state rather than
negligence, but it means Phase 2 must land the token replacement **before** any surface
redesign begins, not alongside it.

Two things are not explained by that root cause and are worse than it:

1. **The landing page ships three fabrications.** Not a style problem — an honesty problem,
   on the one screen a prospective user sees first. See §2, C1/C2.
2. **No skeleton component exists anywhere in the product**, and there is no 404 route and
   no error boundary. These are structural absences, not polish debt. A render exception
   currently white-screens the app.

---

## 2. Consolidated punch list, ranked

Severity is mine, merged across legs. `Leg` names which audit raised it; findings raised by
more than one leg are marked and ranked higher, because independent agreement from different
checklists is the strongest signal in this dossier.

### Critical — fix before or during Phase 2

| # | Finding | Where | Leg | Fix |
|---|---|---|---|---|
| C1 | **Invented metrics rendered as fact.** `"41s"` / "median time to mark a 40-question paper" and `"19.5h"` / "saved per teacher, per month". No traceable source. | `web/src/portals/student/data.ts:228,231` → `Landing.tsx` | hallmark | Delete, or source from the accuracy harness and cite. PRODUCT.md: "Absent — must not be fabricated … no usage numbers." |
| C2 | **Fabricated pricing and a trial that does not exist.** `"EGP 180"`, `"Start 14-day trial"`, and free "for every student of a partnered teacher". PRODUCT.md calls pricing explicitly undecided, puts payments out of scope, and lists partner schools among things that must not be fabricated. | `web/src/portals/student/data.ts:251` | hallmark | Pull the pricing section, or render it as an explicitly labelled placeholder. Three fabrications on one line. |
| C3 | **No React error boundary anywhere in the app.** `grep ErrorBoundary web/src` → zero hits; `App.tsx` has no `errorElement`. A render exception white-screens Lemely. | `web/src/App.tsx:66-125` | diagnose, impeccable | Router-level error boundary in the new language. Purely additive, breaks no deep link. |
| C4 | **No catch-all 404 route.** No `path: "*"` in the router array. | `web/src/App.tsx:66-125` | all three | Designed 404. Also purely additive. |
| C5 | **Mid-render token improvisation** (hallmark gate 48): raw `oklch(...)`, bracket hex, and `text-[62px]` bypassing the token block at ~30 call sites on one screen. `text-[62px]` reinvents the already-defined `.text-display-hero`. | `Landing.tsx` (~30 sites), `Subject.tsx:116,181` | hallmark | Every raw value references a named token. This is a §9 hard gate, so it must be clean before any surface merges. |
| C6 | **Zero pages reflect the Study Notebook system.** Root cause of most of this list. | product-wide; `index.css:1-750`, root `DESIGN.md` | hallmark, impeccable | Phase 2 replaces `DESIGN.md` + tokens first. The existing root `DESIGN.md` is build-era and must not be read as the token source in the interim. |

### Major

| # | Finding | Where | Leg | Fix |
|---|---|---|---|---|
| M1 | **No skeleton component exists in the codebase.** `grep -rl Skeleton web/src` → empty. Every loading state on every screen is a bare `"Loading…"` text node. Exactly the generic-spinner failure the mission names. | product-wide | impeccable, hallmark | Skeleton primitive in Phase 2's component kit; layout-matching skeletons in Phase 3. Highest-leverage single fix in the dossier. |
| M2 | **Em-dash in shipped UI copy**, hard-banned by §3.2.10, across ~25 files and 40+ user-visible strings. | see `hallmark.md` §2a for the full list | hallmark | Restructure with comma or period. Mechanical, but must not be done with a blind sed: comments and non-UI strings are excluded. |
| M3 | **`prefers-reduced-motion` is a blanket `0.001ms` kill** on all animation and transition, product-wide, rather than a designed reduced alternative. Destroys useful feedback instead of calming it. | `web/src/index.css:742-750` | impeccable | Intentional reduced paths per §Phase-5.4. Verified present and blanket. |
| M4 | **The marking wait loses all progress on refresh.** `CorrectPaper` holds pipeline state in component state only — no persistence, no `beforeunload` guard — on the product's longest, highest-stakes, real-latency flow. | `screens/CorrectPaper.tsx` | impeccable | Phase 6.2 explicitly owns this flow. Persist progress; design the recovery. |
| M5 | **No retry-in-place after a marking failure.** The only path forward is re-uploading from scratch. | `screens/CorrectPaper.tsx` | impeccable | Retry affordance on the failure state. |
| M6 | **Empty states absent across the entire parent portal** and ~14 other screens (`EmptyState` grep → zero hits in `portals/parent/screens/*`). A newly linked child's first run is unconfirmed. | parent portal; FlashcardDecks, Practice*, Placement*, Profile, Parents, Onboarding, Grading, ReviewItem, ClassDetail, StudentDetail, MarkSchemes | impeccable | Flagged **unconfirmed, not confirmed-broken** — these may hand-roll empty copy. Confirm per screen in Phase 3 before writing new ones. |
| M7 | **Back navigation exists on 1 of ~40 screens** (`StudentDetail.tsx`). Teacher portal has no breadcrumb at all. | teacher + parent portals | diagnose | Consistent back/breadcrumb affordance. IA proposal 6. |
| M8 | **Interactive div instead of a real control.** `Grading.tsx`'s `PaperCard` is a `role="button"` div with hand-rolled key handling and no `focus-visible` styling, against a codebase convention of real `<Link>`/`<Button>`. | `portals/teacher/screens/Grading.tsx:124-140` | impeccable | Real control. Keyboard + focus come free. |
| M9 | **No brand mark.** The "logo" is a lowercase italic *l* in a filled circle, stamped in three places. | `teacher/index.tsx:194-196`, `parent/index.tsx:91-95`, `auth/ParentLogin.tsx:400` | hallmark | Phase 2 brandkit pass replaces all three stamps. |
| M10 | **Meta/OG tags absent**; one static `<title>` for all 48 routes. No description, no OG, no Twitter card. | `web/index.html` | diagnose | Phase 6.5 closeout. |
| M11 | **No skip-to-content link; no legal links anywhere**, including the marketing landing page. | product-wide | diagnose | Phase 6.5 closeout. |
| M12 | **Full-viewport centred auth hero** — `min-h-screen items-center justify-center` around a centred card, the most recognisable AI auth shape. | `portals/auth/Login.tsx:74` | hallmark | Bias off-centre or let height match content. |
| M13 | **438 raw bracket-pixel values across 37 files.** Many were later promoted to real `--spacing-*` tokens, so this is not uniformly undisciplined, but a real fraction duplicate existing tokens. | product-wide | hallmark | Sweep before Phase 2 locks the new scale, so the new tokens do not inherit the duplication. |
| M14 | **Textbook 3-column feature grid** — three identical kicker→heading→body→bullets cards. | `Landing.tsx:90-124` | hallmark | Break the grid per §4's broken-symmetry rule for marketing. |

### Minor

| # | Finding | Where | Leg |
|---|---|---|---|
| N1 | Spaced hyphen used as a dash in body copy. | `data.ts:200` | hallmark |
| N2 | `font-mono` numerals rely on JetBrains Mono's fixed width rather than an explicit `font-variant-numeric: tabular-nums`. Low real risk today; breaks silently if any of these move to a proportional face. | `xp-streak.tsx:69,78`, `mark-display.tsx:53,56` | hallmark |
| N3 | No offline state distinct from a generic error anywhere sampled, in a PWA. | product-wide | impeccable |

---

## 3. What the audit did NOT verify

Recorded because a gate that did not run is not a gate that passed, and this dossier will be
read later as if it were complete.

- **Nothing was verified against a rendered viewport.** No dev server, no Playwright run, no
  screenshots. Every responsive claim in all three reports is inferred from Tailwind class
  names in source. Contrast, mobile wrap, hero-fits-fold, and touch-target size are therefore
  **unverified, not passed.**
- **Route coverage is partial and stated as such.** hallmark read 13 routes structurally and
  reached the other 34 by sitewide grep only. The grep sweeps are sound for the things greps
  can answer (em-dashes, raw tokens, missing components) and say nothing about layout,
  hierarchy, or flow on those 34 routes.
- **M6's empty-state gaps are "no `EmptyState` component usage found"**, which is not the
  same as "no empty state exists". Confirm per screen before writing replacements.
- The build era's own recorded lesson applies here (`BUILD/DECISIONS.md` D6.12): every gate
  in that build ran against `localhost`, and a condition every harness shares is a condition
  no harness tests. This audit shares the "source-only, no viewport" condition across all
  three legs. The batched Playwright round in Phase 4 closes it; until then it is open.

---

## 4. Proposed IA changes → DECISION D1

Full current page trees per role, nav inventories, and task-path step counts are in
`BUILD/audit/ia.md`. Proposals, each with its cost:

1. **Remove the "Elsewhere" nav group from the student sidebar.** It links an internal
   design-comparison gallery (`/student/directions`) and an orphaned marketing page
   (`/student/landing`) to every real student. Nothing else links to them; no test visits
   them. *Cost: none. Recommend yes.*
2. **Add `/teacher/review` to the teacher sidebar.** The confidence-review queue is a named
   positioning pillar in PRODUCT.md, currently reachable only via conditional CTAs on two
   screens, with no persistent nav path. *Cost: none. Recommend yes.*
3. **Give students an in-app path to `/student/notifications`.** Today the only entry is a
   push deep link, so a student without push has no way in at all. *Cost: none. Recommend
   yes.*
4. **Add a 404 route and a router-level error boundary.** *Cost: none, purely additive,
   cannot break a deep link. Recommend yes.*
5. **Add a consistent back/breadcrumb affordance to the teacher and parent portals.**
   *Cost: low, touches many screens. Recommend yes.*
6. **Scaffold real school-admin and platform-admin screens.** The largest gap. No admin
   portal exists; both roles are deliberately routed into `/teacher` by
   `RequireAuth.tsx:39-48` as an interim the mission's own scope says should end.
   *Cost: high — ~7 new screens, a new route subtree, and un-bundling the `TEACHER_ROLES`
   guard, which `rbac.spec.ts` asserts against.* **This one is not defaulted.** Proposals
   1–5 are cost-free corrections; 6 is a scope decision about how much new product surface
   this redesign builds rather than restyles, and it deserves an explicit answer.

---

## 5. Phase 2 handoff

Ordering that falls out of the above, before any surface work starts:

1. Replace `DESIGN.md` with the Study Notebook system. Until then, the root `DESIGN.md` is
   build-era and is **not** the token source.
2. Land the token replacement in `index.css`, sweeping M13's duplicate bracket values in the
   same pass so the new scale does not inherit them.
3. Add the missing primitives the audit proves absent, not merely unstyled: **Skeleton**
   (M1), EmptyState coverage (M6), ErrorState, and the 404 (C4).
4. Fix C1/C2 in Phase 2 rather than waiting for the marketing surface's turn in Phase 4.
   They are the two findings that would actually harm someone reading them, and they are a
   ten-line data edit, not a redesign.
