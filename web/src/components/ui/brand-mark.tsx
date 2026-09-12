/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import {
  COIL,
  LEFT_FACE,
  MARK_MIRROR,
  MARK_TILT,
  MARK_VIEW_BOX_TIGHT,
  RIGHT_FACE,
  STACK_EDGES,
  type MarkPaint,
  type MarkPath,
} from "@/lib/brandMark"
import { cn } from "@/lib/utils"

/*
 * The Lemely mark: an open spiral notebook, riffling its pages.
 *
 * ── Why the notebook is open ───────────────────────────────────────────────
 *
 * Because a page turn needs somewhere to land. A closed notebook — coil on the
 * left edge, one visible page — can only show a page lifting and vanishing off
 * the side, which reads as a shutter closing, not as a page turning. Putting
 * the coil down the middle gives the mark a left page and a right page, and a
 * sheet can then do the whole real gesture: rise off the right stack, stand on
 * its edge over the gutter, come over, and settle onto the left stack as the
 * new left page. That is the entire reason for the composition.
 *
 * It is also the truthful drawing of what this product is about. The right page
 * is work: a margin, six lines, a dog-eared corner, nothing marked. The left
 * page is the same sheet after it has been turned — and it carries the tick.
 * The mark is not decoration on the mark; it is the state a page arrives in
 * once it has been through the product.
 *
 * ── Why this is a component and not `public/brand/mark.svg` ────────────────
 *
 * Because the mark animates, and an `<img>` cannot animate it honestly.
 *
 * Every header used to render `<img src="/brand/mark.svg">`. An SVG referenced
 * that way is a separate document: it runs no script, and the host page's
 * stylesheet cannot reach inside it. So index.css's global
 * `prefers-reduced-motion: reduce` block — the one that flattens every
 * animation in the product, and the one `motionDefaults.test.ts` guards — stops
 * at the image boundary.
 *
 * The obvious answer is to put the media query inside the SVG file instead.
 * **That does not work, and it was measured rather than assumed.** A probe SVG
 * whose fill changes under `(prefers-reduced-motion: reduce)`, loaded through an
 * `<img>` on a page whose own `matchMedia` for that query returns true, renders
 * the no-preference branch. Chromium does not propagate the preference into an
 * SVG-as-image. The guard would have been a rule with no reader, sitting in the
 * file looking like it worked, while the logo riffled in every header of the
 * product for someone who had explicitly asked it not to.
 *
 * Inline, the mark is back inside the document, where the global block reaches
 * it and where no new gate is needed to make §9.4 true of it.
 *
 * `mark.svg` stays, still, as the source of truth for the surfaces that cannot
 * render React: the favicon `<link>`, and the PWA icons and OG card that
 * `npm run icons` rasterises from it. **The two must be kept in sync,
 * coordinate for coordinate.**
 *
 * ── Where the geometry is ──────────────────────────────────────────────────
 *
 * Not here. `lib/brandMark.ts` holds every coordinate, and
 * `scripts/generate_mark_svg.mjs` writes `public/brand/mark.svg` and
 * `mark-mono.svg` from the same module, so the inline mark and the file cannot
 * drift. This file is the drawing's structure and its motion, nothing else.
 *
 * The one thing it does not share with the files is the artboard: they are
 * square because their consumers are, and this uses the tight landscape box so
 * a header slot is filled rather than letterboxed. `MARK_VIEW_BOX_TIGHT` has
 * the arithmetic.
 *
 * ── How the turn works ─────────────────────────────────────────────────────
 *
 * A turning sheet is TWO elements, not one, because a sheet has two faces and
 * they are not the same drawing:
 *
 *   `.lm-leaf-front` carries the right-page face and rotates 0 to -90 degrees.
 *   `.lm-leaf-back`  carries the left-page face and rotates -90 to -180.
 *
 * They hand over at exactly -90 degrees, where a rotated plane is edge-on and
 * projects to zero width, so the swap costs nothing to look at. This is what
 * lets the back face show the left page the right way round: its content is
 * pre-mirrored about the spine (`translate(64,0) scale(-1,1)`), which the -180
 * degree rotation then un-mirrors, so a landed sheet is the left page exactly —
 * not a reversed copy of the right one.
 *
 * That exactness is what makes the loop seamless. A sheet lands pixel-identical
 * to the left page beneath it and fades out; it is restored later by fading
 * back in over a right page identical to its own front. A cross-fade between
 * two identical images is invisible, so there is no reset to see.
 *
 * `perspective()` sits inside the transform rather than on a parent, so it
 * cannot be lost to a stacking context and needs no `transform-style` on the
 * SVG. Without it `rotateY` degrades to a flat horizontal squeeze — still a
 * turn, just without the foreshortening that sells it.
 *
 * Three sheets run the same two keyframe sets, staggered by `animation-delay`.
 * The stagger is one half-turn, so one sheet is always coming down on the left
 * while the next is going up on the right, and the mark riffles rather than
 * ticking over one page at a time. All three restore together in the cycle's
 * quiet quarter, when nothing is over the right page to cross-fade against.
 *
 * The rest state is the untransformed, fully opaque state, so a reader with
 * reduced motion, a caller passing `animated={false}`, and a rasteriser that
 * ignores CSS all get exactly the same still mark.
 */

export interface BrandMarkProps {
  /** Extra classes; size the mark here, e.g. `h-6 w-6`. */
  className?: string
  /**
   * Riffle the pages. On by default.
   *
   * `false` is for anywhere the mark should hold still regardless of the
   * reader's motion preference — a print stylesheet, a screenshot fixture, a
   * dense surface where a second moving thing would be one too many. It is not
   * the reduced-motion path: that is handled globally in index.css and needs no
   * prop, because a preference the caller has to remember to honour is a
   * preference that will eventually be forgotten.
   */
  animated?: boolean
}

/**
 * Paint, as a CSS custom property rather than a value.
 *
 * `var(--accent)` and friends resolve against `:root` in index.css, so the
 * inline mark follows a token change with no edit here — which the standalone
 * SVG files cannot do, and why the generator resolves the same names through
 * `vite/brandTokens.ts` instead of transcribing hexes into them.
 */
function paint(token: MarkPaint): string {
  return token === "none" ? "none" : `var(--${token})`
}

function Paths({ paths }: { paths: MarkPath[] }) {
  return (
    <>
      {paths.map((path) => (
        <path
          key={path.d}
          d={path.d}
          fill={paint(path.fill)}
          stroke={paint(path.stroke)}
          strokeWidth={path.width}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </>
  )
}

/** Mirrors its children about the spine at x=32. */
function AcrossTheSpine({ children }: { children: ReactNode }) {
  return <g transform={MARK_MIRROR}>{children}</g>
}

/**
 * One turning sheet: a front face for the first half-turn, a back for the
 * second. The back is NOT wrapped in a mirror — `rotateY(-180deg)` about the
 * spine is itself the mirror, and pre-mirroring it as well sends the sheet to
 * the wrong side of the notebook.
 */
function Leaf({ index }: { index: 0 | 1 | 2 }) {
  return (
    <>
      <g className={`lm-leaf lm-leaf-front lm-leaf-${index}`}>
        <Paths paths={RIGHT_FACE} />
      </g>
      <g className={`lm-leaf lm-leaf-back lm-leaf-${index}`}>
        <Paths paths={LEFT_FACE} />
      </g>
    </>
  )
}

export function BrandMark({ className, animated = true }: BrandMarkProps) {
  return (
    /* `aria-hidden`, always: every call site sets the wordmark "Lemely" beside
       this, so describing the mark as well announces the brand twice. */
    <svg
      viewBox={MARK_VIEW_BOX_TIGHT}
      className={cn("lm-mark", !animated && "lm-mark-still", className)}
      aria-hidden="true"
      focusable="false"
    >
      <g transform={MARK_TILT}>
        <AcrossTheSpine>
          <Paths paths={STACK_EDGES} />
        </AcrossTheSpine>
        <Paths paths={STACK_EDGES} />

        {/* The resting pages, then the sheets that turn over them. Leaf 0 is
            drawn last so it is topmost, and it is also the one with no delay:
            the sheet on top of the pile is the sheet that lifts first. */}
        <AcrossTheSpine>
          <Paths paths={LEFT_FACE} />
        </AcrossTheSpine>
        <Paths paths={RIGHT_FACE} />
        <Leaf index={2} />
        <Leaf index={1} />
        <Leaf index={0} />

        <Paths paths={COIL} />
      </g>
    </svg>
  )
}
