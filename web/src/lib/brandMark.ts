/*
 * The Lemely mark, as data: an open spiral notebook, drawn once.
 *
 * ── Why the geometry lives here and not in the drawing ─────────────────────
 *
 * The mark ships in four places that cannot share a renderer:
 *
 *   `components/ui/brand-mark.tsx`  inline SVG in every header, and the only
 *                                   one that animates
 *   `public/brand/mark.svg`         the `<img>`/rasteriser source of truth
 *   `public/brand/mark-mono.svg`    the one-colour cut
 *   the PWA icons and the OG card   rasterised from mark.svg by `npm run icons`
 *
 * The obvious arrangement is to author the SVG by hand and transcribe it into
 * the component with a "keep in sync" comment on both. This repo has found the
 * same defect enough times to know what that comment is worth: it is a rule
 * with no reader, and the two files diverge the first time somebody nudges a
 * curve in one of them.
 *
 * So the coordinates live here, once, and `scripts/generate_mark_svg.mjs`
 * writes the two static cuts from this module. The component imports it
 * directly. Neither can drift from the other because neither owns a coordinate.
 *
 * `mark-favicon.svg` is deliberately NOT generated from this. It is a genuine
 * optical cut for 16x16 — a different drawing, not a resize — and its own file
 * says which features of this one it drops and why each of them measurably
 * fails at four viewBox units per device pixel.
 *
 * ── Colour ─────────────────────────────────────────────────────────────────
 *
 * `stroke` and `fill` below name DESIGN.md tokens, never values. The component
 * emits them as `var(--ink)` and so on, which is why the inline mark tracks a
 * token change with no edit; the generator resolves them through
 * `vite/brandTokens.ts`, which converts the oklch declaration in index.css to
 * hex, so the standalone files cannot carry a transcribed colour either. The
 * mono cut swaps every stroke for `currentColor` and drops every fill.
 *
 * ── The drawing ────────────────────────────────────────────────────────────
 *
 * Everything is authored on the RIGHT half of a 64x64 artboard, from the spine
 * at x=32 outward. The left page is the same data mirrored about the spine.
 * That is not a size saving: it is what lets a turning sheet rotate about x=32
 * and land exactly on the facing page, which is the whole animation.
 *
 * Every edge is a chain of shallow cubics with its control points pulled off
 * true, so no two corners meet at the same angle and no edge is straight. That,
 * plus the two-degree tilt, is the whole of the "doodle" — there is no filter
 * and no roughening pass, the wobble is in the coordinates.
 */

/** A token name from DESIGN.md §3, or the literal `none`. */
export type MarkPaint = "none" | "ink" | "paper" | "paper-raised" | "paper-sunk" | "rule-strong" | "accent"

export interface MarkPath {
  d: string
  fill: MarkPaint
  stroke: MarkPaint
  /** Stroke width in artboard units. The RATIO between these is the design. */
  width: number
}

/**
 * The artboard the standalone cuts use: square, because they feed square
 * consumers — a favicon, the PWA icons, `generate_icons.mjs`'s centred
 * composite — and a square file is what those expect.
 */
export const MARK_VIEW_BOX = "0 0 64 64"

/**
 * The artboard the inline cut uses: the drawn mark, plus a hair.
 *
 * An open notebook is landscape, and it fills 89% of the square artboard across
 * but only 67% of it down. An `<svg>` fits its whole viewBox inside its CSS box,
 * so a square viewBox in an `h-6 w-6` header slot draws a notebook 16px tall in
 * 24px of space, letterboxed above and below — the mark rendering a third
 * smaller than the room it was given, in every header in the product. Widening
 * the CSS box does not help; the square viewBox is the constraint.
 *
 * These numbers are the mark's measured extent (0.8936 x 0.6748 of the square
 * artboard, centred at 32, 32.4) rounded outward. `generate_icons.mjs` measures
 * the same extent from the rendered alpha at build time for its safe-zone
 * arithmetic, and will fail loudly if the mark outgrows its own artboard.
 */
export const MARK_VIEW_BOX_TIGHT = "2 9.5 60 45"
export const MARK_TILT = "rotate(-2 32 32)"
/** Mirrors right-half geometry onto the left page. */
export const MARK_MIRROR = "translate(64,0) scale(-1,1)"

/**
 * The right page: work, unmarked, with a dog-eared outer corner.
 *
 * No margin rule. It belongs against this page's left edge, which here is the
 * gutter, and there it sits a stroke's width from the coil — at 24px the two
 * merge into one red smear down the middle of the mark. Moved to the outer edge
 * instead it runs into the dog-ear. The left page carries the one margin rule
 * in the mark, where it has a clear edge to itself and a tick to hold.
 */
/** The right page's outline. Named because the loading cut redraws it. */
const RIGHT_SHEET = `M32 12.8 C39 12.1, 46 13, 53 12.4
  C55 12.2, 56.4 12.6, 57.4 12.3
  C58.1 22, 57.3 32, 57.5 41.4
  C57.6 43.2, 57.5 44.5, 57.4 45.6
  C55.6 47.5, 53.4 49.4, 51.2 51.2
  C44.6 51.6, 38.4 50.7, 32 51.3 Z`

/** The left page's outline: no dog-ear, so its outer edge runs straight down. */
const LEFT_SHEET = `M32 12.8 C39 12.1, 46 13, 53 12.4
  C55 12.2, 56.4 12.6, 57.4 12.3
  C58.1 22, 57.3 32, 57.5 41.4
  C57.6 45.4, 57.4 48.5, 57.3 50.7
  C48 51.5, 40 50.6, 32 51.3 Z`

/** The tick, authored backwards because its face is mirrored into place. */
const TICK = `M46.4 41 C45.5 42.2, 44.4 43.7, 43.4 45
  C41.8 41.9, 40.4 37.6, 39 33.6`

export const RIGHT_FACE: MarkPath[] = [
  // The sheet. Its outer bottom corner is cut for the dog-ear that follows.
  {
    d: RIGHT_SHEET,
    fill: "paper-raised",
    stroke: "ink",
    width: 1.15,
  },
  // The dog-ear: the corner turned down, its underside showing. The flap is
  // `paper` where the stack behind it is `paper-sunk`; that one step of tone is
  // the only thing separating the folded corner from the gap it was folded out
  // of. BRAND.md §2 has the folded corner in territory — "return here, progress
  // kept by hand" — and it earns its place twice over, because it breaks the
  // one corner of the silhouette that would otherwise be a plain rectangle.
  {
    d: `M57.4 45.6 C55.8 46.6, 54 47.2, 52.4 47.6
        C52.1 48.9, 51.6 50.2, 51.2 51.2 Z`,
    fill: "paper",
    stroke: "ink",
    width: 1,
  },
  // Six lines of writing, each a different length, the last one short: that is
  // what a page of worked answers looks like. Hairlines by design — 0.95
  // against the tick's 1.9 — so at a glance they read as texture and only
  // resolve into separate lines when the mark is shown large.
  { d: "M39.4 19.5 C43.6 18.9, 49 20, 54.2 19.2", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M39.5 25 C42.8 24.5, 47 25.4, 50.6 24.7", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M39.4 30.5 C44 29.9, 49.6 31, 54.8 30.2", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M39.5 36 C42.4 35.5, 45.6 36.3, 49 35.7", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M39.4 41.5 C42.6 41, 46.4 41.9, 52.4 41.1", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M39.5 47 C41.2 46.6, 43 47.2, 45.4 46.7", fill: "none", stroke: "rule-strong", width: 0.95 },
]

/**
 * The left page: the same sheet, turned over, and marked.
 *
 * Authored on the right half like `RIGHT_FACE` and mirrored into place, so it
 * reads back-to-front in the source. That is the price of one rotation origin
 * for both faces, and it is paid once here rather than in every keyframe.
 */
export const LEFT_FACE: MarkPath[] = [
  {
    d: LEFT_SHEET,
    fill: "paper-raised",
    stroke: "ink",
    width: 1.15,
  },
  // The margin rule, down this page's left edge — which after the mirror is the
  // notebook's outer edge. This is the old Lemely mark, kept: BRAND.md §2 calls
  // the margin "the strongest single idea available", and the previous logo was
  // little else.
  {
    d: "M53.6 15.2 C53.9 24, 53.5 33, 53.8 41.6 C53.9 45, 53.7 47.4, 53.8 48.8",
    fill: "none",
    stroke: "accent",
    width: 0.8,
  },
  { d: "M51.4 19.5 C47 18.9, 40.4 20, 35.2 19.2", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M51.3 25 C48 24.5, 42.6 25.4, 38.6 24.7", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M51.4 30.5 C47.5 29.9, 41.2 31, 36.4 30.2", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M51.3 36 C48.6 35.5, 45 36.2, 42.5 35.7", fill: "none", stroke: "rule-strong", width: 0.95 },
  { d: "M51.4 41.5 C49.8 41.1, 48.4 41.6, 47 41.2", fill: "none", stroke: "rule-strong", width: 0.95 },
  // The correction. The heaviest stroke in the mark and the only one a hand
  // made, which is why it is the one thing here that is not ruled, not printed
  // and not straight. It is on the left page because the left page is the sheet
  // that has already been through the product.
  //
  // It is drawn BACKWARDS — short arm on the right, long arm running down and
  // to the left — because this face is mirrored into place. On screen it lands
  // as an ordinary tick. Everything else on this face is close enough to
  // symmetrical that the mirror does not show; a tick is not, and a reversed
  // one is the single thing here a reader would notice.
  { d: TICK, fill: "none", stroke: "accent", width: 1.9 },
]

/**
 * The block of sheets under one page, drawn as the two edges of it that show.
 * Two steps rather than one: a single backing line reads as a doubled outline
 * where two read as a pad. Depth by tonal layering and offset, never by shadow
 * (DESIGN.md §7).
 */
export const STACK_EDGES: MarkPath[] = [
  {
    d: `M58.4 14 C59.1 23.6, 58.4 33.4, 58.6 42
        C58.7 46, 58.5 49.2, 58.4 51.6
        C49 52.4, 41 51.5, 33.4 52.2`,
    fill: "none",
    stroke: "ink",
    width: 1,
  },
  {
    d: `M59.4 15.2 C60.1 24.6, 59.4 34.2, 59.6 42.8
        C59.7 46.6, 59.5 49.8, 59.4 52.4
        C50 53.2, 42 52.3, 34.4 53`,
    fill: "none",
    stroke: "ink",
    width: 1,
  },
]

/**
 * The coil. Drawn over both pages, because it wraps over them — and because a
 * sheet crossing the gutter has to pass beneath it, which is where a page bound
 * into a coil actually goes.
 *
 * Four rings: enough to read as a continuous binding, few enough that the gaps
 * between them survive at 24px instead of filling in and turning the gutter
 * into a solid red bar. Each is flatter than the pitch that separates it — 5
 * units tall at 9 apart — because a ring as tall as its own gap reads as a
 * ladder rung rather than as wire crossing a gutter.
 */
const COIL_RINGS = [15.7, 24.7, 33.7, 42.7].map(
  (y) => `M27.9 ${y + 5} C27.1 ${y + 1.9}, 29.2 ${y - 0.1}, 32 ${y}
    C34.8 ${y + 0.1}, 36.7 ${y + 2}, 35.9 ${y + 5}`,
)

export const COIL: MarkPath[] = COIL_RINGS.map((d) => ({
  d,
  fill: "none" as const,
  stroke: "accent" as const,
  width: 1.5,
}))

/**
 * The mark reduced to its silhouette, in the order a hand would draw it.
 *
 * This is the loading cut. `components/ui/mark.tsx` draws it stroke by stroke
 * for the slow-load tier, and `vite/preMountShell.ts` writes it into
 * `index.html`'s pre-mount shell — the two surfaces that were still carrying
 * the PREVIOUS mark, each as its own hand-transcription of an SVG file that no
 * longer contains that geometry. They read from here now, so there is one mark
 * in the product rather than three drawings of two different ones.
 *
 * It is the silhouette and not the whole mark on purpose. Watching eleven
 * hairlines of ruling draw themselves is noise, not reassurance, and the shell
 * version sits in `index.html`'s critical path where twenty-six paths is real
 * weight for a difference nobody can see at 24px. Four steps say "notebook,
 * bound, marked", which is the whole job.
 *
 * `mirrored` means the step belongs inside the `MARK_MIRROR` group: the left
 * page and the tick are authored on the right half like everything else here.
 */
export interface MarkOutlineStep {
  /** Identifies the step's animation class: `lm-draw-<step>`, `lm-shell-<step>`. */
  step: "page-right" | "page-left" | "coil" | "tick"
  paths: string[]
  stroke: MarkPaint
  width: number
  mirrored: boolean
}

export const MARK_OUTLINE: MarkOutlineStep[] = [
  { step: "page-right", paths: [RIGHT_SHEET], stroke: "ink", width: 1.6, mirrored: false },
  { step: "page-left", paths: [LEFT_SHEET], stroke: "ink", width: 1.6, mirrored: true },
  { step: "coil", paths: COIL_RINGS, stroke: "accent", width: 2, mirrored: false },
  { step: "tick", paths: [TICK], stroke: "accent", width: 2.6, mirrored: true },
]
