# Quality bar — every frontend change must clear this before merge

This file is the checklist. It is referenced by `MISSION.md` §6 gate 8, by the
`designer` and `visual-qa` agents, and by CI. A change that fails any line here
does not merge, regardless of whether the feature "works."

## Visual
- [ ] Uses only colours defined in `DESIGN.md` / the token file. No stray hex
      values, no arbitrary Tailwind values (`text-[#1a1a1a]`, `p-[13px]`) in
      components. Grep proves it.
- [ ] All text meets WCAG AA contrast (≥ 4.5:1 normal, ≥ 3:1 large). Verified by
      axe, not by eye.
- [ ] Spacing follows the 4px scale; type follows the defined scale. No one-off
      sizes.
- [ ] Corner radii and shadows come from the token set and are consistent
      across components of the same class.
- [ ] No placeholder assets, lorem ipsum, greyed-out boxes, or "Logo here".
      Real content or a designed empty state.
- [ ] Dark mode (if the design is dual-mode) has contrast and hierarchy parity
      with light — not merely inverted.

## UX
- [ ] Every form input has a visible, associated label. Placeholder text is
      never the only label.
- [ ] Validation is present, inline, and states how to fix the problem.
- [ ] Navigation is present and correct for the role (student bottom nav,
      teacher/admin sidebar) and shows the current location.
- [ ] Every interactive element has hover, focus, active, and disabled states.
- [ ] Empty, loading, error, and offline states exist and are designed — not a
      bare spinner or a blank region.
- [ ] Destructive actions confirm; long operations report progress; completed
      actions confirm with a message that matches the action's verb.
- [ ] Copy is specific and plain. No "Submit", no "Oops! Something went wrong."

## Responsive
- [ ] Works from 320px up. **No horizontal scroll at any breakpoint** — tested,
      not assumed.
- [ ] Layouts verified at 380 / 768 / 1440.
- [ ] Navigation collapses gracefully on small screens.
- [ ] Touch targets ≥ 44×44px on mobile, with adequate spacing between them.
- [ ] Content reflows rather than shrinking to illegibility.

## Accessibility
- [ ] Zero serious or critical axe violations. Lighthouse accessibility ≥ 95.
- [ ] Semantic HTML: one h1 per page, heading order unbroken, landmarks
      (`main`, `nav`, `header`) present.
- [ ] All meaningful images have alt text; decorative images are `alt=""`.
- [ ] Keyboard: every interactive element reachable, in a logical order, with a
      visible focus indicator. Modals trap focus and restore it on close.
- [ ] ARIA only where semantics are insufficient, and correct where used.
- [ ] **Colour is never the sole carrier of meaning.** The correct/partial/wrong
      scale, the confidence scale, and every error state must be legible in
      greyscale — icon, text, or shape as well as colour. This is a hard
      requirement of this product, not a generic a11y note.
- [ ] `prefers-reduced-motion` respected by every animation.
- [ ] Live regions announce async results (marking complete, validation errors).

## Code quality
- [ ] Zero console errors and zero unhandled promise rejections on every route.
- [ ] Reuses the existing component library. No duplicated Button/Card/Input
      variants; if a new primitive is genuinely needed it is added to the
      library and the catalogue, not inlined.
- [ ] TypeScript clean, oxlint clean, no `any` introduced.
- [ ] No TODO comments, commented-out code, dead props, or unused imports in the
      final diff.
- [ ] No hardcoded strings that should be data; no mock data left in a wired
      screen.

## Product-specific (non-negotiable — from `docs/LEMELY_UI_SPEC.md`)
- [ ] Every displayed mark carries its confidence, and low confidence is
      impossible to miss.
- [ ] Any predicted grade or boundary derived from incomplete data is visibly
      labelled "estimated".
- [ ] No screen accuses a student of cheating; integrity flags are teacher-only
      and phrased as signals.
- [ ] No screen anywhere ranks students by grades, marks, or percentages.
- [ ] Teacher-corrected marks are shown as corrections, attributed.

## Security / compliance
- [ ] No third-party scripts added without a recorded decision.
- [ ] External links use `rel="noopener noreferrer"`.
- [ ] No secrets, tokens, or internal URLs in client code.
- [ ] User-generated content is escaped; no `dangerouslySetInnerHTML` without a
      sanitiser and a recorded reason.

## Evidence required in the phase report
- [ ] Screenshots for every screen × state × breakpoint touched.
- [ ] axe summary (violation counts by severity, per route).
- [ ] Lighthouse scores per route.
- [ ] `npx impeccable detect src/` output.
- [ ] Visual diff result against the committed baselines.
