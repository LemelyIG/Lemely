# Hallmark audit — Lemely web SPA (Phase 1, redesign leg)

Audited by: hallmark `audit` verb, run against `/home/sico/Lemely/web/src` on branch `redesign/phase-0`.
Scope: 47 routes across student/teacher/parent/auth/settings portals (`web/src/App.tsx`,
`web/src/portals/{student,teacher,parent}/index.tsx`). Gradio excluded per mission scope.
Method: full reads of the router files, the shared component library
(`components/ui/*`), and a representative set of screens (auth, marketing/landing,
paper-result, leaderboard, teacher overview); sitewide `grep` sweeps for every
pattern-detectable gate (em-dash, emoji, gradients, inline oklch/hex, icon-library
mixing, `transition-all`, `hover:scale`, fake chrome, invented-metric phrasing,
exclamation-mark copy) across every `.tsx` file in scope. **This is not a
line-by-line read of all 55 screen files** — see §3/§4 for exactly what was and
wasn't read in depth.

---

## 1. Verdict

Close, but not close for the reason a typical hallmark audit finds — this codebase's
engineering discipline (state handling, honest-data comments, a single icon library,
no `transition-all`, no fake browser/phone chrome anywhere, no bounce easings, no
mismatched icon sets) is unusually high for an AI-touched React app, and the button/
card/type primitives already lean toward the flat-hairline, solid-ink, serif+sans+mono
system the redesign mission wants. But the product currently ships the **wrong design
system entirely**: every token in `index.css` traces to `DESIGN.md`'s "Academic
Warmth" Material-3 terracotta/teal palette, not the "Study Notebook" warm-paper
identity the redesign mission mandates — there is no notebook texture, no marginalia,
no handwritten accent face, and the "logo" is a lowercase italic *l* in a circle. On
top of that gap, the one screen built as this app's marketing surface (`Landing.tsx`)
independently fails several hard hallmark gates on its own terms — invented metrics,
a rendered EGP price PRODUCT.md says is undecided, a textbook 3-column feature grid,
and inline `oklch()`/pixel literals that bypass the token block entirely — and the
whole product ships a hard-banned typographic tell (the em-dash) in dozens of pieces
of real, shipped UI copy. Nothing here is unfixable, and most of the fixes are
additive (new tokens, new texture layer, new copy pass) rather than structural
teardown, but as it stands this ships as slop against the Study Notebook mandate:
zero pages currently read as "notebook," and the landing page specifically ships
content a stricter honest-copy read would block on its own.

**5 critical · 6 major · 3 minor** (counted below; some criticals recur across
multiple files and are listed once with all locations).

---

## 2. Ranked punch list

| # | Sev | Tell | Where | Fix |
|---|---|---|---|---|
| C1 | critical | Invented metrics | `web/src/portals/student/data.ts:227-232` → rendered `Landing.tsx:126-147` | Replace `"41s"` / `"19.5h saved per teacher, per month"` with `—` + "metric to confirm," or source them from the accuracy harness before shipping |
| C2 | critical | Fabricated/undecided pricing presented as final | `web/src/portals/student/data.ts:249-252` → rendered `Landing.tsx:150-186` | PRODUCT.md states pricing is explicitly undecided; do not render `"EGP 180"` / `"Revenue share"` as if a decision was made — placeholder or pull the pricing section |
| C3 | critical | The 3-column feature grid | `Landing.tsx:90-124` (`pillars`, `grid-cols-3`, kicker → heading → body → bullet-list, identical card shape ×3) | Break the grid: vary widths, drop a card, or move to typographic rhythm per `macrostructures.md` |
| C4 | critical | Mid-render token improvisation (gate 48) | `Landing.tsx:32,62,68,70,72,80,84,91,95,101,104,107,110,114,116,126,128,131,135,139,141,142,151,152,156,159,162,167,172,177` (raw `text-[Npx]`, `oklch(...)`, bracket hex) · `Subject.tsx:116,181` (`bg-[oklch(...)]`) | Every raw value must reference a named token; `text-[62px]` on `Landing.tsx:32` duplicates the *already-defined* `.text-display-hero` utility instead of using it |
| C5 | critical | Full-viewport centred hero (auth) | `portals/auth/Login.tsx:74` — `<main className="flex min-h-screen items-center justify-center ...">` wrapping a centred form card | Let the auth screen's height match its content, or bias the card off-centre; this is the single most-recognised AI auth-screen shape |
| M1 | major | Em-dash in shipped UI copy (hard-banned by REDESIGN-MISSION §3.2.10) | Dozens of call sites — see §2a below for the full list | Restructure with a comma or period, or use `,` — never `—`, in any string a user reads |
| M2 | major | No catch-all/404 route | `web/src/App.tsx:66-125` — router array has no `path: "*"` entry | Add a designed 404 in the Study Notebook language before Phase 6 closes out |
| M3 | major | Zero pages reflect the mandated design system | Product-wide — `index.css:1-750`, `DESIGN.md:1-198` | Root cause of most other findings; Phase 2 must replace `DESIGN.md` + tokens before any screen redesign, not after |
| M4 | major | System-managed project ships no stamp of allegiance | Every `.tsx` file in scope | `hallmark audit`'s own rule: a `design.md`-governed project should stamp which system a page follows; none do (no Hallmark stamp convention exists here yet — expected, since Phase 2 hasn't run, but flagged per audit protocol) |
| M5 | major | Raw bracket-pixel values instead of the named scale (gate 24) at scale | 438 occurrences across 37 files (`grep -roE "\[[0-9]+(\.[0-9]+)?px\]"`) | Not all are undisciplined — many were later promoted to `--spacing-*px` tokens in `index.css` — but a real fraction (Landing above) duplicate tokens that already exist. Sweep before the redesign locks new tokens |
| M6 | major | No brand mark — the "logo" is a lowercase italic *l* in a filled circle | `portals/teacher/index.tsx:194-196`, `portals/parent/index.tsx:91-95`, `portals/auth/ParentLogin.tsx:400` | Placeholder, not a mark; Phase 2's brandkit logo pass replaces this everywhere it's stamped |
| N1 | minor | Hyphen used as a dash in body copy | `web/src/portals/student/data.ts:200` — `"...partnered teacher - No card to start"` | `—`(U+2014) or restructure; presently a spaced hyphen, not even the banned em-dash — still a proofreading tell |
| N2 | minor | Loading states are bare "Loading…" text, not layout-matching skeletons | `components/ui/state-views.tsx:150-156` (`RouteFallback`), `portals/teacher/screens/Overview.tsx:63-72` | Not a hard hallmark gate, but `motion.md`'s stated preference; worth a Phase 3/6 pass |
| N3 | minor | `font-mono` numerals rely on JetBrains Mono's fixed width instead of an explicit `tabular-nums` declaration | `components/ui/xp-streak.tsx:69,78`, `mark-display.tsx:53,56` | Low real risk (monospace glyphs are already fixed-width) but add `font-variant-numeric: tabular-nums` for correctness if any of these ever move to a proportional face |

### 2a. M1 — full em-dash location list (UI copy only, comments excluded)

`portals/teacher/screens/Announcements.tsx:192` · `Review.tsx:449` · `QuizBuilder.tsx:152,270,372,447` ·
`AtRiskList.tsx:143,325` · `ClassAnalytics.tsx:83` · `Quizzes.tsx:235` ·
`portals/student/screens/Standings.tsx:208,483,519` ·
`portals/student/screens/flashcards/FlashcardReview.tsx:113,122,211,276` ·
`portals/student/screens/flashcards/FlashcardDecks.tsx:136,249,353,477` ·
`portals/student/screens/practice/PracticeGenerator.tsx:324,346` ·
`portals/student/screens/practice/PracticePrint.tsx:29,38` ·
`portals/student/screens/placement/PlacementInvite.tsx:128` ·
`portals/student/screens/Announcements.tsx:222,320,346` ·
`portals/student/screens/Notifications.tsx:224` ·
`portals/student/screens/Profile.tsx:318` ·
`portals/student/screens/Parents.tsx:39` ·
`portals/settings/NotificationSettings.tsx:65,75,188` ·
`portals/parent/screens/ChildOverview.tsx:59` ·
`portals/parent/screens/Children.tsx:114,125` ·
`portals/teacher/screens/ReviewItem.tsx:118,206,284,561,570` ·
`components/quiz/QuizTaker.tsx:378,388,599,600` ·
`components/ui/confidence-indicator.tsx:38,44`.

(Not flagged: the many bare `"—"` glyphs used as a *missing-value placeholder* in
tables — e.g. `QuizResults.tsx:77,229,247,314,327,436`, `ClassRoster.tsx:135,319`,
`AtRiskList.tsx:211` — that is a defensible, common UI convention for "no data," not
the prose em-dash the mission bans.)

### Blockers, in prose

**C1/C2 (Landing.tsx honesty).** This is the most serious finding in the audit
because it isn't a taste problem, it's a truth problem. PRODUCT.md is explicit:
*"Absent — must not be fabricated: no customers, no testimonials, no case studies,
no press, **no pricing**, no live deployment, no usage numbers, no partner schools."*
`Landing.tsx` currently renders `"EGP 180"` as a real per-month price and `"19.5h
saved per teacher, per month"` as a real proof stat, both sourced from a static
`data.ts` array with no traceable measurement behind them. Hallmark's own gate 46
would fail this on sight even without the project's stricter PRODUCT.md rule.

**C3 (3-column grid).** The `pillars` section is the canonical AI template almost
verbatim: three equal-width cards, each with a mono kicker above a serif heading
above two lines of body above a bulleted list, identical shape three times in a row.
This is doubly notable because the rest of the product avoids this pattern
completely — it's isolated to the one screen that was clearly built fastest.

**C4 (token bypass).** The token system in `index.css` is genuinely well-built —
every color traces to a named `--md-*` role with a documented provenance comment,
which is more rigor than most hand-built design systems get. `Landing.tsx` throws
that discipline away with raw `oklch()` literals and bracket pixel values, including
reinventing `--fs-display-hero` (62px, already a token: `.text-display-hero`) as a
bare `text-[62px]` two lines after the file imports `Card` from the component
library it otherwise respects.

**C5 (centred auth hero).** `Login.tsx`'s own code comment calls this screen
"infrastructure to exercise the auth plumbing... not final UI" — so this finding is
expected, not a surprise, but it is still exactly the shape hallmark names as the
single most-recognised AI landing pattern (`min-h-screen`, everything centred, one
card). Flagging it here so it's on the Phase 4 auth-surface punch list explicitly.

---

## 3. Per-route coverage

Legend: **Full** = read the screen file end-to-end for structure, hierarchy, and
copy · **Partial** = read a meaningful portion (noted) · **Grep** = not read as a
file, but covered by every sitewide pattern sweep in this audit (em-dash, emoji,
gradient, inline color, icon-library, motion tells, fake chrome, invented-metric
phrasing) · **Not reached** = no coverage at all.

| Route | Screen file | Coverage |
|---|---|---|
| `/` | `App.tsx` `Root` | Full |
| `/login` | `portals/auth/Login.tsx` | Full |
| `/login/parent` | `portals/auth/ParentLogin.tsx` | Grep only |
| `/settings/devices` | `portals/settings/DeviceSettings.tsx` | Grep only |
| `/settings/notifications` | `portals/settings/NotificationSettings.tsx` | Grep only |
| `/student` | `portals/student/screens/Overview.tsx` | Grep only |
| `/student/subject/:code` | `screens/Subject.tsx` | Partial (grep hits read in context, lines 116/181) |
| `/student/result/:paperId` | `screens/PaperResult.tsx` | Partial (first 140 of a larger file) |
| `/student/correct` | `screens/CorrectPaper.tsx` | Grep only |
| `/student/plan/:subjectCode` | `screens/studyplan/StudyPlanWeek.tsx` | Grep only |
| `/student/plan/:subjectCode/session/:sessionId` | `screens/studyplan/StudyPlanSession.tsx` | Grep only |
| `/student/board` | `screens/Standings.tsx` | Partial (first 120 lines) |
| `/student/announcements` | `screens/Announcements.tsx` | Grep only |
| `/student/notifications` | `screens/Notifications.tsx` | Grep only |
| `/student/friends` | `screens/Friends.tsx` | Grep only |
| `/student/profile` | `screens/Profile.tsx` | Grep only |
| `/student/parents` | `screens/Parents.tsx` | Grep only |
| `/student/onboard` | `screens/Onboarding.tsx` (+ `onboarding/QuestionnaireStep.tsx`, `SubjectsStep.tsx`) | Grep only |
| `/student/placement/:subjectCode` | `screens/placement/PlacementInvite.tsx` | Grep only |
| `/student/placement/test/:assignmentId` | `screens/placement/PlacementTest.tsx` | Grep only |
| `/student/placement/result/:assignmentId` | `screens/placement/PlacementResult.tsx` | Grep only |
| `/student/practice/:subjectCode` | `screens/practice/PracticeGenerator.tsx` | Grep only |
| `/student/practice/set/:assignmentId` | `screens/practice/PracticeSet.tsx` | Grep only |
| `/student/practice/result/:assignmentId` | `screens/practice/PracticeResult.tsx` | Grep only |
| `/student/practice/print/:assignmentId` | `screens/practice/PracticePrint.tsx` | Grep only |
| `/student/flashcards/:subjectCode` | `screens/flashcards/FlashcardDecks.tsx` | Grep only |
| `/student/flashcards/review/:subjectCode` | `screens/flashcards/FlashcardReview.tsx` | Grep only |
| `/student/landing` | `screens/Landing.tsx` | **Full** |
| `/student/directions` | `screens/Directions.tsx` | Grep only |
| `/teacher` | `portals/teacher/screens/Overview.tsx` | Partial (first 100 lines) |
| `/teacher/grading` | `screens/Grading.tsx` | Grep only |
| `/teacher/review` | `screens/Review.tsx` | Grep only |
| `/teacher/review/:itemId` | `screens/ReviewItem.tsx` | Grep only (heavy em-dash hits reviewed in context) |
| `/teacher/classes` | `screens/Classes.tsx` | Grep only |
| `/teacher/classes/:classId` (layout) | `screens/ClassDetail.tsx` | Grep only |
| `/teacher/classes/:classId` (index) | `screens/ClassRoster.tsx` | Grep only |
| `/teacher/classes/:classId/analytics` | `screens/ClassAnalytics.tsx` | Grep only |
| `/teacher/students/:studentId` | `screens/StudentDetail.tsx` | Grep only |
| `/teacher/at-risk` | `screens/AtRiskList.tsx` | Grep only |
| `/teacher/schemes` | `screens/MarkSchemes.tsx` | Grep only |
| `/teacher/quizzes` | `screens/Quizzes.tsx` | Grep only |
| `/teacher/quizzes/:quizId` | `screens/QuizBuilder.tsx` | Grep only |
| `/teacher/quizzes/:quizId/assignments/:assignmentId/results` | `screens/QuizResults.tsx` | Grep only |
| `/teacher/announcements` | `screens/Announcements.tsx` | Grep only |
| `/parent` | `portals/parent/screens/Children.tsx` | Grep only |
| `/parent/children/:childId` | `screens/ChildOverview.tsx` | Grep only |
| `/parent/children/:childId/subjects/:code` | `screens/SubjectDetail.tsx` | Grep only |
| `/parent/children/:childId/weaknesses` | `screens/Weaknesses.tsx` | Grep only |

**Layout shells — full reads:** `App.tsx`, `portals/student/index.tsx`,
`portals/teacher/index.tsx`, `portals/parent/index.tsx`.

**Shared component library — full reads:** `components/ui/card.tsx`, `button.tsx`,
`primitives.tsx`, `state-views.tsx`, `grade-badge.tsx`, `mark-display.tsx`,
`xp-streak.tsx`, `processing-state.tsx`, `trend-sparkline.tsx` (partial, first 40
lines). **Not read:** `boundary-bar.tsx`, `checkbox.tsx`, `chip.tsx`,
`confidence-indicator.tsx` (grep only), `nav-shells.tsx`, `paper-identity.tsx`,
`question-row.tsx`, `role-switcher.tsx`, `slider.tsx`, `stepper.tsx`,
`weakness-chip.tsx`, `components/quiz/QuizTaker.tsx` (grep only),
`components/CameraCapture.tsx` (grep only), `components/teacher/Avatar.tsx`,
`components/teacher/StatCard.tsx`.

**Design tokens — full read:** `web/src/index.css` (all 750 lines), `DESIGN.md`
(first 60 lines of 198 — frontmatter + enough to confirm it is the pre-redesign
"Academic Warmth" system, not read further since the rest is the same YAML
continuing).

---

## 4. What I could not verify

- **34 of 47 routes got pattern-sweep coverage only, not a structural read.** I
  cannot certify hero shape, card-grid symmetry, centred-layout gates (6, 44, 45),
  or nav/footer archetype choices (42, 43) for any "Grep only" row in §3 — I can
  only certify that those files contain no em-dash/emoji/gradient/inline-color/
  mixed-icon/fake-chrome/invented-metric hits, because those are literal-string
  greps that don't require reading rendered structure. A grep cannot catch "3
  equal-height cards" or "everything centred" — those require the read I didn't do
  for those 34 files. C3 (3-column grid) and C5 (centred hero) were only caught
  because Landing.tsx and Login.tsx happened to be in the "Full" set.
- **I did not render or screenshot any screen.** Every finding here is static-code
  reading. Contrast gates (40/41), hero-fits-the-fold (44b), mobile wrap behaviour
  (49–55), and sticky-overlap (56) all require a rendered viewport to verify and
  are **entirely unverified** in this audit. `BUILD/QUALITY-BAR.md` and the
  project's own `check_ui_gates.py`/Puppeteer gates (referenced in code comments
  across `Landing.tsx`, `Overview.tsx`, `state-views.tsx`) appear to already run
  some of these checks in CI — I did not run them.
  - Ran `rg`/`grep` only, no `npm run build`, no dev server, no Playwright.
- **No `.hallmark/log.json` or `/* Hallmark · macrostructure: ... */` stamp exists
  anywhere in the repo** — confirmed by grep across `web/src` and repo root. This
  means the diversification rule (gate 8, 20, 32) and the stamp-vs-page check from
  `verbs/audit.md` have nothing to check against yet; that's expected pre-Phase-2,
  not a finding.
- **`DESIGN.md` at repo root is the pre-redesign "Academic Warmth" system**, not
  the Study Notebook system this mission will produce in its own Phase 2. I audited
  the current code against hallmark's universal anti-pattern list and against
  REDESIGN-MISSION.md's binding rules (§3.2, §4), not against `DESIGN.md`'s own
  rules, since `DESIGN.md` itself is scheduled for replacement. If a future
  hallmark audit is run after Phase 2 writes the real `DESIGN.md`, it should
  re-check every route in §3 against that file per `verbs/audit.md`'s
  `design.md`-audit branch, which this pass did not use.
- **Card-in-card (gate 4).** I ran a rough grep (`<Card` occurrence density) that
  was too noisy to trust and did not manually verify any true nested-card
  instance — no finding either way; unverified, not cleared.
- **Contrast on the amber/warn tokens, the confidence scale, and the grade-band
  scale** — `index.css`'s own comments show extensive, hand-documented WCAG
  contrast work (lines 57–98) with specific ratios cited, which reads as credible,
  but I did not independently recompute any of it.
- I did not check `Gradio` (out of scope per the mission) or the backend/API layer.
