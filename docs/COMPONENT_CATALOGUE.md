# Component catalogue — Phase 2.5 cross-cutting library

Every component named in `docs/LEMELY_UI_SPEC.md` §4 (C-1..C-13), built on the
`web/src/index.css` token layer (D2.10 / P2.5.1). All live in
`web/src/components/ui/`. Later phases compose these; they do not invent new
primitives without adding them here (MISSION §4).

Verified together: `npx tsc --noEmit` clean, `npm run build` clean, `npm run
lint` (oxlint) clean — zero new warnings beyond the pre-existing
`only-export-components` pattern already present across the codebase.

## C-1 — Grade badge
`grade-badge.tsx` — `GradeBadge({ grade, size, basis, estimated })`
- `size`: `hero` / `medium` / `inline`.
- `basis`: `achieved` (solid fill, grade-band color) vs `predicted`
  (outlined on surface — provisional by construction).
- `estimated`: forces a dashed border + a permanent "Estimated" label
  regardless of `basis` — an achieved grade can still rest on an estimated
  boundary lookup. Satisfies the "never invent precision" product principle.
- Exports `gradeBand(grade)` (also used by `boundary-bar.tsx`).

## C-2 — Mark display
`mark-display.tsx` — `MarkDisplay({ awarded, available, size, showPercent })`
- `size`: `hero` (display type scale) / `inline` (mono figures).
- "58 / 80" format + optional percentage.

## C-3 — Boundary bar
`boundary-bar.tsx` — `BoundaryBar({ score, maxScore, boundaries, estimated })`
- Segmented track colored by grade band, tick labels, "You — X/Y" marker,
  distance-to-next-boundary readout.
- `estimated`: dashed-border "Estimated boundaries" treatment.
- Empty `boundaries`: honest "Boundary data isn't available for this paper
  yet" message — never fabricates a boundary.

## C-4 — Confidence indicator
`confidence-indicator.tsx` — `ConfidenceIndicator({ tier, className })` (per-
question compact) and `ConfidenceIndicatorSummary({ confident, uncertain,
needsReview })` (per-paper aggregate).
- Three tiers (`confident` / `uncertain` / `needs-review`), each with its own
  icon (`CheckCircle` / `WarningCircle` / `Flag`) plus the `confidence-*`
  color tokens — quiet/unfilled when confident, filled+bordered+labeled when
  not. Survives greyscale.
- Tap-to-expand plain-language explanation (a real disclosure, not
  hover-only, so it works on touch).
- The most novel component per the UI spec — this is the primary trust
  surface for the marking product.

## C-5 — Weakness chip
`weakness-chip.tsx` — `WeaknessChip({ topic, severity, meta, variant, onClick })`
- `severity`: `minor` / `moderate` / `significant`, rendered as a 1/2/3-bar
  signal glyph + `aria-label` (not color alone). Reuses `t3`/`warn`/`err` —
  no dedicated severity token exists yet.
- `variant`: `list` (full row) / `grid` (tile) / `inline` (compact pill).
- Renders as `<button>` when `onClick` is given (drills into evidence).

## C-6 — Question row
`question-row.tsx` — `QuestionRow({ number, awarded, available, state, confidence, topic, expanded, onToggle, children })`
- Composes C-2 (inline `MarkDisplay`) and C-4 (compact `ConfidenceIndicator`).
- `state`: `correct` / `partial` / `wrong`, each with its own icon
  (`CheckCircle` / `CircleHalf` / `XCircle`) over the `mark-*` tokens — the
  canonical color-is-not-the-only-signal case per QUALITY-BAR.
- Boxed question-number cell (exam-margin motif); controlled or uncontrolled
  expand/collapse for question detail.

## C-7 — Paper identity line
`paper-identity.tsx` — `PaperIdentity({ code, session, paperLabel })`
- "0580/42 · May/June 2023 · Paper 4 Variant 2" in `text-metadata`
  (JetBrains Mono) — consistent naming everywhere a paper is referenced.

## C-8 — Trend sparkline
`trend-sparkline.tsx` — `TrendSparkline({ ... })`
- Pure SVG polyline, no charting library. Directional read (`up`/`down`/
  `flat`) always paired with an icon + text label, never shape/color alone.
- Empty-state message when there are no attempts yet.

## C-9 — XP / streak indicator
`xp-streak.tsx` — `XPStreak({ variant, streakDays, frozen, xpTotal, level, weeklyXp, days, sources })`
- `variant`: `compact` (nav) / `expanded` (profile, adds a 7-day dot
  calendar + XP-source breakdown).
- `frozen` swaps the flame icon for a snowflake (shape, not just color) and
  mutes tone.
- Numbers render in `font-mono`, deliberately never the serif display face
  used for marks — this component must never look like it's showing a
  grade. No grade/mark prop exists on it by design (leaderboards/XP
  principle).

## C-10 — Processing state
`processing-state.tsx` — `ProcessingState({ stages, footer })`
- Multi-stage pipeline (read pages → identify paper → fetch scheme → mark
  questions → analyse), each `ProcessingStage` independently `pending` /
  `active` / `done` / `error`.
- `error` requires a real, specific `errorMessage` — the component renders
  nothing generic if omitted; no fallback "something went wrong" text exists
  anywhere in it.
- Optional `progress: {current, total, unit}` on the marking stage for
  "Question 7 of 21".
- Discrete per-stage glyphs + connecting stem, not a single animated bar —
  the explicit "resist a fake progress bar" requirement from the UI spec.
  Only the truly-active stage animates (a spinner), governed by the global
  `prefers-reduced-motion` rule already in `index.css`.

## C-11 — Empty / error / offline state family
`state-views.tsx` — `StateView({ kind, icon, tone, heading, body, action, secondaryAction })` + named wrappers `EmptyState` / `ErrorState` / `OfflineState`.
- One shared layout (icon circle / heading / body / action) across all three
  conditions, per the spec's "design a family, not one-offs" instruction.
- `error` defaults to the `warn` (amber) tone rather than `err` (red), per
  PRODUCT.md's guidance to avoid red-heavy error states for exam-stressed
  students; `tone` can override to `err` where genuinely warranted.

## C-12 — Role switcher
`role-switcher.tsx` — `RoleSwitcher({ roles, currentRoleId, onSwitch })`
- Accessible menu (`aria-haspopup`, `aria-expanded`, `role="menu"`,
  `role="menuitemradio"` + `aria-checked`), closes on outside-click/Escape.
- **Open question, documented in-file and in D2.10**: the UI spec names C-12
  once with no placement/trigger detail and no screen shows it. Built as a
  self-contained trigger; the P2.5.3 retrofit (or a later phase, if no
  current screen needs it) decides where it's actually mounted.

## C-13 — Navigation shells
`nav-shells.tsx` — `BottomNav` (mobile tab bar, student) and `SidebarNav`
(desktop vertical list, teacher/admin), both driven by a shared
`NavShellItem[]` (`id, label, icon, href?, onClick?, active, badge?`) — no
hardcoded routes.
- Both set `aria-current="page"` on the active item and reuse the exact
  focus-visible ring treatment from `button.tsx`.
- `item.href` renders a plain `<a>` for now; the P2.5.3 retrofit swaps in
  `react-router`'s `NavLink` where SPA routing is needed.

## C-14 — Checkbox
`checkbox.tsx` — `Checkbox({ label, ...inputProps })` (P3.8 chunk b)
- Not named in the UI-spec §4 C-1..C-13 list — added because T-07's
  bulk-approve needs a real multi-select control and nothing else in the
  library provides one.
- Native `<input type="checkbox">` (free keyboard/AT semantics), visually
  restyled via `appearance-none` + a `has-checked:`/`has-focus-visible:`
  driven wrapper box — the real input stays in the accessibility tree rather
  than being hidden behind a decorative sibling.

## C-15 — Stepper
`stepper.tsx` — `Stepper({ steps, current, onSelect, completed, disabled })` (P3.8 chunk c)
- Not named in the UI-spec §4 C-1..C-13 list — added because T-09's six-step
  quiz builder needs a real step-navigation control and nothing else in the
  library provides one.
- Every step is a real `<button>`, always reachable — the builder never
  gates which step a teacher may jump to, even once a quiz is read-only
  ("read-only" disables each step's own form controls, not navigation
  itself — a teacher must still be able to browse what was configured).
  `completed` renders a check mark instead of a number for a step that
  already has a value (a hint only, never a gate). `disabled` swaps every
  button for a plain `<span>` — not used by the quiz builder itself, kept
  for a future flow that needs to disable navigation too.
- `aria-current="step"` on the active step; native buttons carry full
  keyboard/AT semantics for free.

## C-16 — Slider
`slider.tsx` — `Slider({ value, onValueChange, min, max, step, "aria-label" })` (P4.8 chunk A)
- Not named in the UI-spec §4 C-1..C-13 list — added because S-02's weekly-
  study-time and per-topic confidence questions need a real range input and
  nothing else in the library provides one.
- Native `<input type="range">` restyled via `accent-accent` (keyboard/AT
  semantics free); `py-9px` wrapper gives the thumb a >=44px touch target
  without inflating the visible 6px track past DESIGN.md's meter rhythm.
- Deliberately owns no "skipped" state — that is a screen-level decision
  (D4.5): the caller (`QuestionnaireStep.tsx`'s `SkippableSlider`) tracks
  whether the student has touched the control and renders its own "Not set"
  affordance before the first interaction, so an unmoved slider never reads
  as an answer the student gave.

## Known follow-ups for the P2.5.3 retrofit
- Two pre-token-system components duplicate new library components and
  should be deleted in favor of the new ones once screens are retrofitted:
  `web/src/portals/student/components/viz.tsx::Bar` (superseded by C-3/C-8)
  and `web/src/portals/student/components/BoundaryRail.tsx` (hardcoded
  `oklch()` gradient, superseded by C-3 `boundary-bar.tsx`).
- No `--color-on-error` token is exposed from `index.css`; `xp-streak.tsx`
  used `text-white` directly where that was needed. Revisit if more
  components need an on-error text color — may be worth promoting to a
  named token rather than repeating the literal.
- Weakness-chip severity (C-5) and the state-view error tone default (C-11)
  both reuse existing tokens (`t3`/`warn`/`err`) rather than adding new
  dedicated ones — call out if a genuine gap surfaces during retrofit.
