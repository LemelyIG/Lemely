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

## Tutoring marketplace components (C-17..C-24, T15)

Defined in `docs/tutoring/SPEC.md` §d. Pure layout and copy logic lives in
`web/src/lib/tutoring/` so the node-only unit runner can test it; the
components are thin. All are token-only and use logical properties. The shared
rules: every chart has a real table alternative, no meaning is carried by
colour alone, ordinal data stays ordered, an under-threshold figure says it is
hidden instead of drawing an empty chart, and `loading` is a skeleton of the
same shape. Error and offline states belong to the fetching screen (C-11, via
`QueryState`). The copy rule (`check:copy`) bans "improvement" and "verified"
in all of these files.

## C-17 — Ordinal distribution
`ordinal-distribution.tsx` — `OrdinalDistribution({ ladder, distribution, subjectName, loading })`
- Horizontal stacked bar over the ordered ladder from `Outcomes.ladder`
  (never declared in the frontend). Pure SVG in percentages. Segments take the
  grade-band colours of C-1 via `gradeBand`; each is labelled with grade and
  count, and a label moves below the bar (with a leader line, spread apart)
  when its segment is too narrow to hold it.
- Every rung is listed under the bar, a rung nobody reached as 0. Caption
  states `n` (and how many more have no grade). "Show as table" toggles a real
  `<table>` with a caption. The chart is `role="img"` with a full-sentence
  label that speaks every rung.
- `state: "insufficient"` renders the C-11 compact empty state with S-34's copy,
  `k` taken from the figure. So does a "sufficient" figure whose graded count
  (`nGraded`, else the buckets) is under `k`: a second guard, so a bad payload
  cannot show a small group. The hidden state shows `k` and never a count.
  Logic: `lib/tutoring/ordinalLayout.ts` (`distributionHidden`).

## C-18 — Grade change summary
`grade-change-summary.tsx` — `GradeChangeSummary({ change, headingAs, loading })`
- Three-part bar, "Lower grade · Same grade · Higher grade", with
  `ArrowDown` / `Equals` / `ArrowUp` and a count each, `n` caption and the same
  table toggle. Title fixed in code ("Change in grade while with this tutor"),
  not a prop.
- Neutral by design: a light-to-dark ink ramp, no grade-band, green or red
  colour, so a lower grade is not drawn as a mark against the tutor. Each list
  item pairs a swatch of its segment's fill with its icon, word and count, so
  the segments are not told apart by lightness alone.
- Insufficient state as C-17, including the second guard on `nPaired` under `k`.
  Logic: `lib/tutoring/gradeChange.ts` (`gradeChangeHidden`).

## C-19 — Slot picker
`slot-picker.tsx` — `SlotPicker({ slots, value, onChange, loading, disabled, disabledReason })`
- Day chips (wrapping) and the times of the chosen day, both native radio
  groups, so arrow keys move within each group. Slots are grouped by the
  tutor's calendar day in the tutor's zone, with the zone label in the legend;
  a day without times is still a chip ("No times") and shows "No times on this
  day." when chosen. A repeated hour when the clocks go back carries its UTC
  offset, so no label stands for two instants. The chosen day and the chosen
  time each show a check, and the time is repeated in words.
- `onChange` takes `Slot | null`: when a refetch no longer offers the chosen
  time, the picker calls `onChange(null)` (judged only on settled data, not
  while `loading`), so a request is never sent for a time that is gone. A time
  still offered is kept, and so is the day being looked at while it is in the
  window. Logic: `lib/tutoring/slotGroups.ts` (`isSelectionStale`,
  `resolveActiveDay`).

## C-20 — Booking status
`booking-status.tsx` — `BookingStatus({ state })`
- Icon and word for each of the eight effective states (SPEC §a.3), on the
  status `Chip`; every state has its own label and its own icon. Renders the
  state the API computed; never derives one from times. Logic:
  `lib/tutoring/bookingStatus.ts`.

## C-21 — Notes thread
`notes-thread.tsx` — `NotesThread({ notes, viewer, canPost, frozen, zone, zoneLabel, onPost, onReport, ... })`
- Notes oldest first with author label and tutor-zone time; plain text only,
  never auto-linked. A hidden note reads "Removed by Lemely" and has no Report
  button. Fixed line "Notes can be reported. Lemely staff read notes only when
  one is reported."; a tutor's composer always adds "This student's parents can
  read these notes."; a frozen thread shows "Notes are paused while Lemely looks
  at a report." and no composer. A parent's thread is read-only but reportable.
  What the foot shows is decided by `notesComposerState` (tested), not by the
  component. `onPost` must return a promise (`mutateAsync`): the box clears on
  success and keeps the text on a rejection.
- A refused contact detail reads "To keep everyone safe, keep contact details
  off Lemely." in the composer (the SPEC §d sentence points at the session
  notes, which would be circular here) and sits on the field; any other
  failure is an alert line under it. Every other free-text sheet uses the SPEC
  §d sentence. Copy: `lib/tutoring/safetyNoticeCopy.ts`
  (`NOTES_CONTACT_DETAILS_MESSAGE`, `CONTACT_DETAILS_MESSAGE`).

## C-22 — Rating summary
`rating-summary.tsx` — `RatingSummary({ rating })`
- "4.6 · 12 students" (one decimal) with one star glyph, or a "New" pill below
  three students; never a row of stars. The whole thing is one `role="img"`
  with a full-sentence label. A "rated" rating with no average or fewer than
  three students is shown as New. Logic: `lib/tutoring/ratingLabel.ts`.

## C-23 — Tutor card
`tutor-card.tsx` — `TutorCard({ tutor, to, headingAs })`
- Public name, headline, C-22, subject tags (`SubjectTag`), ways to meet as
  icon plus word, and the area. With `to`, the name is a link stretched over the
  whole card. Shows only `TutorCard` fields, so it is safe on the open web.

## C-24 — Safety notice sheet
`safety-notice-sheet.tsx` — `SafetyNoticeSheet({ open, onAcknowledge, pending, error })`
- The first-booking notice on `Modal`, not dismissible: no close control, no
  Escape, no scrim click; the one "I understand" button calls `onAcknowledge`
  (S15). Title, five paragraphs and button are fixed by the SPEC and parsed from
  it by `safetyNotice.test.ts`. The five paragraphs are the `Modal`
  `description` (the dialog's `aria-describedby`), because `Modal` focuses the
  button on open and a screen-reader user must hear the notice first.

## Report and block sheets (T15)
- `web/src/components/tutoring/report-sheet.tsx` —
  `ReportSheet({ open, onClose, targetType, targetLabel, onSubmit, pending, error, sent })`.
  One sheet for every Report: reason (required, the seven `reportreason`
  values; the disputed outcome only on a booking), optional words (1000
  characters, the database limit, tested against migration 0050), the helpline
  beside a safety concern, a "Report sent" view that keeps the helpline after a
  safety concern. A failed send (duplicate report, rate limit) is an alert line,
  not an error on the optional words.
- `web/src/components/tutoring/block-sheet.tsx` —
  `BlockSheet({ open, viewer, counterpartName, onConfirm, onCancel, pending, error })`.
  Lists the effects of a block (SPEC §a.2) before the button; not dismissible
  by accident; "Block" and "Don't block". A block ends sight of progress
  through the tutoring pages only: the copy says that a school class the tutor
  teaches still shows the class progress, and a student is told their grades
  stop counting in that tutor's results. Both built on `Modal` (focus moves in,
  is trapped, and returns on close), with copy in `safetyNoticeCopy.ts`.

## Session view, review form and stop-sharing sheet (T23)
- `web/src/components/tutoring/session-detail-view.tsx` —
  `SessionDetailView({ booking, viewer, tutorHref, countingHref, cancel, complete, reviews, notes, safetyNotice })`.
  S-37 and P-06 (SPEC §d) share it: it draws one booking for a `"student"` or
  `"parent"` viewer, and every role-specific write comes in as a prop (`cancel`,
  `complete`, `reviews`, `notes.post`, `safetyNotice`), so the parent screen
  supplies the parent hooks and leaves out what a parent does not have. Controls
  come from `sessionActions` (`allowedActions`; a parent also needs
  `requestedBy === "parent"`), never from the state. Inside 24 hours it says why
  there is no Cancel; a tutor's late cancellation shows their reason as plain
  text; a system cancellation reads "This session was cancelled by Lemely." and
  never the stored reason (SPEC §i.8). A meeting link is an anchor only for an
  http(s) address, with `rel="noopener noreferrer"`. Reporting (R1) is inside the
  view. C-21 is composed with the C-24 gate: a student's first note waits for the
  notice when the settings say it is unread (the draft stays in the box), and
  the server's 409 `safety_notice_required` brings the sheet up as well. Offline,
  Cancel and Mark as completed are disabled with the reason. Exports its prop
  types (`SessionAction`, `SessionReviewActions`, `SessionNotesInput`,
  `SessionSafetyNotice`). Logic and every sentence: `lib/tutoring/sessionView.ts` (including the
  `usePagedItems` "show more" hook shared by S-36, the notes and the S-38 log).
- `web/src/components/tutoring/review-form.tsx` —
  `ReviewForm({ mode: "create" | "edit", initialStars, hasText, onSubmit, onCancel, pending, error })`.
  Native radio group for the stars (44 px targets, filled shape plus "n of 5
  stars", arrow keys), optional text (1000 characters), the SPEC privacy line.
  Edit sends only what changed (the booking carries the stars, not the old text,
  so the box means "replace" and "Remove my review text" clears it).
- `web/src/components/tutoring/stop-sharing-sheet.tsx` —
  `StopSharingSheet({ open, grant, onConfirm, onCancel, pending, error })`.
  Not dismissible by accident; the class line appears only when
  `alsoTeachesClasses` has a name in it, and the "still counted in their results"
  line is always there (SPEC §d S-38). Copy: `lib/tutoring/accessView.ts`.

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
