# Abyss design system migration and teacher home

Date: 2026-11-02
Branch: `design/teacher-home-variants` (worktree `.claude/worktrees/teacher-home-variants`)
Status: approved in brainstorming, awaiting spec review

## Goal

Move the whole web app from the retired "Study Notebook" system to Brand Guidelines v5
"Abyss" as documented in `DESIGN.md`, and ship the two teacher screens prototyped in
`web/dev-previews/teacher-home.html` and `web/dev-previews/teacher-empty.html` as real,
data-backed React screens.

Success means:

1. Every screen in `web/src` renders with the `DESIGN.md` Material 3 roles, fonts, radii and
   spacing, in light and dark themes.
2. No retired token name remains in `web/src`, and a test enforces that.
3. `/teacher` shows the setup state for a new teacher and the full home once setup is done,
   both matching the prototypes and backed by real API data only.

## Scope

In scope:

- The token layer in `web/src/index.css` and `web/src/portals/marketing/brand-tokens.css`.
- A rename of every retired utility class across `web/src` (about 195 files).
- Hand fixes for uses that a mapping cannot express.
- The teacher Overview home, the teacher setup (empty) state, and the teacher shell (sidebar
  and top bar).
- Five additive, read-only backend fields that the teacher home needs.

Out of scope:

- Adding Binny to student screens that do not already have it. Binny already in the
  marketing portal stays; Binny on any teacher, parent or admin surface is removed.
- New features on any other screen. Other screens change only visually.
- Copy rewrites beyond what the token and brand rules require (confidence shown as a
  percentage, the never-say list).

## Part 1: token layer and rename

### Tokens

`web/src/index.css` replaces its Study Notebook tokens with the `DESIGN.md` set:

- Material 3 colour roles as `--md-*` custom properties: light values on `:root`, dark values
  under `:root[data-theme="dark"]`. The names follow `DESIGN.md` frontmatter (`primary`,
  `on-primary`, `primary-container`, ..., `surface-container-lowest` ... `highest`,
  `outline`, `outline-variant`, `inverse-*`, `scrim`, `shadow`).
- Custom colours: `--md-success`, `--md-gold` (tertiary), the Jewel grade scale
  (`--grade-a-star` ... `--grade-u`).
- Radius tokens: `bar 4`, `row 10`, `chip 12`, `button 14`, `inner 18`, `tile 20`, `card 24`,
  `board 32`, `pill 999`.
- Font tokens: `--font-display` (Bricolage Grotesque Variable), `--font-ui` (Schibsted Grotesk
  Variable), `--font-mono` (JetBrains Mono Variable).
- Motion tokens: `--ease-out` `cubic-bezier(0.2, 0.8, 0.2, 1)`, `--ease-expo`
  `cubic-bezier(0.16, 1, 0.3, 1)`, durations 150 / 200 / 350ms.
- Shadows: `--shadow-hover`, `--shadow-panel` (values in `DESIGN.md` Elevation).

Deleted: the Caveat font and every `font-hand` use, the paper texture layer, the pastel
tokens, the subject colours, and the old dark ladder.

The Tailwind `@theme inline` block maps each role to utilities, for example
`bg-surface-container-low`, `text-on-surface-variant`, `bg-primary-container`,
`text-on-primary-container`, `border-outline-variant`, `text-error`, `bg-grade-a`,
`rounded-card`, `font-display`.

`web/src/portals/marketing/brand-tokens.css` stops defining its own colour values and reads the
same `--md-*` roles, so there is one source of colour.

### Rename

A mapping table, checked into the repo next to the codemod, lists every retired utility and
its replacement. The first plan task completes it from a full scan of `web/src`; the starting rows are:

| Retired | Replacement |
|---|---|
| `text-ink` | `text-on-surface` |
| `text-ink-muted`, `text-ink-faint` | `text-on-surface-variant` |
| `text-ink-inverse` | `text-inverse-on-surface` |
| `bg-ink` | `bg-inverse-surface` |
| `bg-paper` | `bg-surface` |
| `bg-paper-raised` | `bg-surface-container-lowest` |
| `bg-paper-sunk` | `bg-surface-container-low` |
| `bg-paper-inverse` | `bg-inverse-surface` |
| `border-rule` | `border-outline-variant` |
| `border-rule-strong` | `border-outline` |
| `bg-accent`, `text-accent`, `border-accent` | `bg-primary`, `text-primary`, `border-primary` |
| `text-accent-on` | `text-on-primary` |
| `text-accent-ink` | `text-on-primary-container` |
| `bg-accent-wash` | `bg-primary-container` |
| `text-accent-hover` | `hover:bg-primary-hover` or `text-primary` (decided per use) |

The codemod (a Node script under `web/scripts/`) rewrites class names in `.tsx`, `.ts` and
`.css` files under `web/src`, including variant prefixes (`hover:`, `dark:`, `md:`) and
opacity suffixes (`/50`). It is idempotent: a second run changes nothing.

Uses the table cannot express are fixed by hand, portal by portal: pastel tags, subject
colours, marginalia components, `font-hand`, hard-coded colours (2 found), and any radius or
font size off the `DESIGN.md` scale.

### Guard

A vitest file scans `web/src` and fails if any retired token or utility name appears
(`paper-*`, `ink-*`, `rule-*`, `accent-*`, `pastel-*`, `subject-*`, `font-hand`, `Caveat`).
It must be shown to fail on a planted retired name before it is trusted.

## Part 2: teacher home and setup state

### Routing

`/teacher` renders `TeacherHome`. It loads `useTeacherOverview()` and `useTeacherClasses()`,
derives setup progress, and renders `TeacherSetup` until all three steps are done, then the
full `Overview`.

### Setup progress (pure function, unit-tested)

`deriveSetup(classes, overview)` returns `{ created, uploaded, reviewed }`:

- `created`: the teacher has at least one class.
- `uploaded`: `overview.paperCount > 0`.
- `reviewed`: `uploaded` is true and `overview.pendingReviewCount === 0`.

No new tracking field and no localStorage. Progress always reflects the account.

### TeacherSetup

Ports `teacher-empty.html` and `teacher-empty.js`:

- Hero with "Create a class" and "Upload papers" actions.
- Three steps with the progress bar, done ticks and the "N of 3 done" live region.
- Create goes to `/teacher/first-class` (existing `CreateFirstClass`). Upload opens the existing
  paper upload flow and accepts a page-wide PDF drop once a class exists; before that it
  nudges step 1. Review goes to `/teacher/review`.
- Delight from the prototype: join-code settle, step nudge, progress fill, "All set". Every
  animation is off under `prefers-reduced-motion`.
- The marking progress shown in the prototype uses real job status if the upload flow
  exposes it; otherwise the step shows "Marking" until the overview reports the papers.

### Overview

Ports `teacher-home.html`, split into components under
`web/src/portals/teacher/components/overview/`:

- `ReviewQueueTile`: pending count (Bricolage, 64px), "answers below 70% confidence" copy,
  confidence histogram from `reviewConfidenceBuckets`, 70% threshold marker, axis 0% to 100%,
  link to the queue with "about N min" from `reviewEstimateMinutes`.
- `MarkClassSet`: drop zone and upload action, with the "Big tick" received animation.
- `ClassStrip`: class cards (name, code, student count, grade chip, delta, top weak topic)
  with horizontal scroll.
- `AtRiskTable`: flat link rows (avatar, name, reason summary, previous grade to current
  grade), divided by 1px `outline-variant` lines, hover as in the prototype.
- Teacher shell: sidebar with nav, "Your classes" list and tools, the top bar with quieter
  utilities. The content well keeps 72px side margins and the top bar 28px.

Every tile has loading, error and zero states. No number is shown that does not come from
the API.

### Backend

In `lemely/web/schemas_teacher.py` and the overview query:

- `OverviewDTO.paperCount: int`: papers uploaded across the teacher's classes.
- `OverviewDTO.pendingReviewCount: int`: review items awaiting the teacher.
- `OverviewDTO.reviewConfidenceBuckets: list[int]`: 10 counts, one per 10% confidence band,
  over the teacher's pending review items.
- `OverviewDTO.reviewEstimateMinutes: int`: `ceil(pending_count * SECONDS_PER_REVIEW / 60)`,
  with `SECONDS_PER_REVIEW` a named constant (initially 20) documented as a heuristic. The UI
  labels it "about".
- `AtRiskStudentDTO.previousGrade: str | None`: the grade from the student's paper before
  the latest one, or `None` when there is no earlier paper.

Each field gets pytest coverage, including the empty case, and is mirrored in
`web/src/lib/teacherTypes.ts`. Fields are additive, so older clients keep working.

## Testing

- Vitest: `deriveSetup` truth table; each overview tile's loading, error, zero and data
  states; the retired-token guard (proven red first).
- Pytest: the five new backend fields, run file by file (no full suite locally).
- Playwright screenshots of `/teacher` (setup and full) and one screen per other portal, light
  and dark, at 1440 and 375 wide.
- Gates from `ci.yml` (lint, typecheck, `check:copy`, the impeccable hooks) run before review.

## Rollout and rollback

All work stays on `design/teacher-home-variants`. The token swap and rename land as separate
commits from the teacher screens, so either can be reverted alone. The backend fields are
additive and need no migration.

## Risks

- The rename touches about 195 files. Mitigation: one mapping table, an idempotent codemod,
  and review by mapping rule instead of by file.
- Dark mode contrast: the old ladder was AA-measured. The new dark roles must be measured
  for AA on text roles before merge.
- `ci.yml` may include visual baselines that the restyle invalidates. They are regenerated
  deliberately, not skipped.
