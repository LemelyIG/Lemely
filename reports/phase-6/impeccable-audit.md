# P6.7 — `/impeccable audit` pass over the frontend source

Run 2026-08-12 (session 104) against `web/src/` at `46bd5f7`, following
`.claude/skills/impeccable/reference/audit.md`. Scope as MISSION §4 words it:
*"run `/impeccable audit` across all frontend source"*.

**Read this alongside the measured gates, not instead of them.** Four of the
five dimensions below are also measured empirically by the audit runner
(`web/scripts/audit.mjs`) on every route-state, and where the two disagree the
measurement wins — a source read cannot see a contrast ratio that a rendered
page can. The value of this pass is the two things the runner cannot see:
design-system drift and touch-target sizing.

---

## 0. A finding about the tooling, before any finding about the product

**`npx impeccable detect` is vacuous on this machine, and `scripts/check.sh`'s
`impeccable-detect` gate therefore proves nothing.**

impeccable 3.5.0 returns `[]` for `web/src/` — and also for every file written
deliberately to trip it:

| Probe | Result |
|---|---|
| `src/` (2 400+ lines of TSX across 41 screens) | `[]`, exit 0, zero bytes |
| A `.tsx` with `style={{color:"#ff0000"}}` inline | `[]` |
| A `.css` with `font-size: 13.7px; line-height: 0.9` | `[]` |
| A `.ts` with fourteen em-dashes (an *advisory* rule the CLI documents) | `[]` |

Identical under `--json`, `--quiet` and `--no-config`. No project config
suppresses anything — `.impeccable/config.local.json` holds only the hook
consent flag.

So MISSION §4's *"resolve every finding"* is satisfied trivially, and MISSION
§6 gate 8's *"`npx impeccable detect` clean"* is a green light that measures
nothing. **Not chased further**: it is third-party tooling, the deterministic
checks that do bite (axe, Lighthouse, console-error, horizontal-scroll) are
unaffected, and this pass is the non-vacuous half of the same requirement.
Recorded here and in DELIVERY.md rather than counted as a pass.

---

## 1. Audit Health Score

| # | Dimension | Score | Key finding |
|---|---|---|---|
| 1 | Accessibility | 4 | Zero axe violations at **any** impact across every audited route-state, over five phases. Lighthouse a11y floor 96. |
| 2 | Performance | 3 | The bundle is split (P6.1: 1.3 MB entry → 397 kB / 90 chunks). CLS from late-arriving content was the live defect and is fixed on `student-standings`; the *pattern* it came from is not audited elsewhere. |
| 3 | Theming | 2 | Zero hardcoded colours anywhere — but ~600 arbitrary Tailwind literals across 41 files bypass tokens that exist for them. Single-theme by design. |
| 4 | Responsive | 3 | Zero horizontal-scroll violations at 380/768/1440 across the whole corpus. 54 `size="sm"` controls sit near 31px tall — WCAG 2.2 AA (24px) met, AAA (44px) not. |
| 5 | Implementation integrity | 3 | Coherent and unmistakably product-specific. The drift is confined to spacing/type literals, and it is one-directional: the Phase-2.5 retrofit held, later phases did not extend it. |
| **Total** | | **15/20** | **Good** — address dimension 3. |

## 2. Implementation Integrity verdict — **PASS**

The implementation expresses a coherent, product-specific system, and the
evidence is that its details are not interchangeable with another product:
`BoardRow` distinguishes a `null` streak from a `0` streak because absent is
not zero; `RouteFallback` is deliberately *not* a `StateView` because a
sub-second chunk gap is not a terminal answer about data; `StateView`'s error
kind defaults to amber rather than red because PRODUCT.md's accessibility note
says so. Those are decisions with reasons attached, not template output.

The detector is silent (§0), so this verdict rests on reading, not on it.

## 3. Findings by severity

### [P1] ~600 arbitrary Tailwind literals bypass tokens that already exist

- **Location**: 41 `.tsx` files. Worst: `portals/student/screens/Landing.tsx`
  (69), `Subject.tsx` (60), `Directions.tsx` (43), `teacher/screens/Review.tsx`
  (41), `Grading.tsx` (36).
- **Category**: Theming / design-system drift.
- **Impact**: Phase 2.5's acceptance criterion was *"the token file is the only
  source of design values — grep proves no stray hex codes or arbitrary
  spacing in components."* That was true of the screens it retrofitted and has
  not held since: every screen built in Phases 3–5 reintroduced literals. The
  tokens are not missing — `web/src/index.css` defines `--spacing-13px`,
  `--spacing-18px`, `--spacing-9px` and the rest *specifically* as the DESIGN.md
  rungs these call sites need, so `py-[13px]` is a bypass of `py-13px`, not a
  gap in the system. The cost is that a DESIGN.md spacing change now needs a
  600-site edit instead of a one-line one.
- **Not fixed, deliberately.** A mechanical 600-site rewrite at ship time is a
  large uninspectable diff whose only acceptance signal is a screenshot compare
  that cannot be pixel-clean by construction (the seed's `run_tag` is random
  per run). The risk of a silent visual regression exceeds the benefit of a
  cleanup nothing is blocked on. Carried into DELIVERY.md as a known
  limitation with the file list above.
- **Suggested command**: `/impeccable normalize` per screen, one portal at a
  time, in a phase that can afford a re-baseline.

### [P2] 54 `size="sm"` controls are below the 44px touch target

- **Location**: `components/ui/button.tsx:35` (`sm: "btn-text-sm px-3.5 py-2"`,
  12.5px type → ~31px box), and the 54 `size="sm"` call sites.
- **Category**: Accessibility / responsive.
- **Impact**: WCAG 2.2 **AA** (2.5.8 Target Size Minimum, 24×24) is met, so
  this is not a conformance failure and axe correctly reports nothing. WCAG
  2.5.5 **AAA** (44×44) is not met. It matters most on the student surfaces,
  which PRODUCT.md describes as phone-first.
- **Already known**: carried since the Phase-2.5 report §8 as a deferred gap.
  Re-confirmed here rather than rediscovered.
- **Suggested command**: `/impeccable adapt`.

### [P2] The late-content layout-shift pattern is fixed on one screen, not audited on the rest

- **Location**: fixed in `portals/student/screens/Standings.tsx`; the pattern
  is `x.isPending ? null : <block/>` above other content.
- **Category**: Performance.
- **Impact**: This is what took `student-standings` to CLS 0.386 and
  performance 74. Lighthouse only fails a route when the skeleton happens to
  paint before the data lands, so the same defect can sit on other screens at
  a passing score and surface later on a slower machine — which is exactly the
  history of this one (92 on one run, 74 on the next, same tree).
- **Partly mitigated by measurement**: every route in the corpus now carries a
  `layout-shifts` audit in `reports/phase-6/lighthouse/*.json`, so the next
  pass can rank screens by real CLS instead of by grep.
- **Suggested command**: `/impeccable optimize`, ranked off that JSON.

### [P3] Single-theme by design, so "both themes" does not apply

- `prefers-color-scheme`, `.dark` and `data-theme` appear **zero** times in
  `index.css`, and `dark:` appears **zero** times across all `.tsx`.
- MISSION §11's screenshot policy says *"and both themes **if** the design is
  dual-mode"*. It is not. Recorded so a reader of the corpus does not conclude
  the dark captures were skipped.

## 4. Positive findings — keep these

- **Zero hardcoded colours.** Not one `#hex`, `rgb()` or `hsl()` in any `.tsx`
  or `.ts` under `web/src/`. Colour is fully tokenised; the drift in §3 is
  spacing and type only.
- **Comments carry the reason, not the restatement.** `Standings.tsx` explains
  why the pinned viewer row is a `<div>` and the ranked rows are `<li>` (a
  listitem with no list parent is a serious axe violation). That is the class
  of note that stops a future edit from silently undoing a fix.
- **Accessibility is the strongest dimension in the build and has been for
  three phases.** Zero axe violations at any impact, sustained while the route
  count grew from 4 to 24 to 44.
