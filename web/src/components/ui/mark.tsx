/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V5 */
import { MARK_MIRROR, MARK_OUTLINE, MARK_TILT, MARK_VIEW_BOX_TIGHT } from "@/lib/brandMark"

/*
 * The Lemely mark, drawing itself.
 *
 * `animated` is the "still loading" reading: a single small mark redrawing
 * itself in place is a legitimate one-glance answer to "is this stuck?" for the
 * rare case a whole page has nothing else to show yet (`slow-load`, PR 2's
 * `FullPageState`). It is not a general-purpose spinner — `Button`'s `loading`
 * prop and `RouteFallback` already own the ordinary in-flight cases — and its
 * one call site is deliberately kept to that single rare case. The
 * `stroke-dashoffset` this needs is DESIGN.md §9.2's one documented exception
 * to "animate only transform and opacity".
 *
 * ── What changed when the mark did ─────────────────────────────────────────
 *
 * This file used to carry its own transcription of `public/brand/mark.svg` —
 * the previous mark, an `L` of two hairlines with a tick across it — with a
 * comment saying so. `index.html`'s pre-mount shell carried a second
 * transcription of the same three paths. When the mark was redesigned as an
 * open notebook, both kept drawing a logo that no longer existed anywhere else
 * in the product, and neither had anything watching. That is the transcription
 * hazard `lib/brandMark.ts` exists to end: the geometry has one home, and this
 * reads it.
 *
 * It draws `MARK_OUTLINE` — the mark's silhouette rather than the whole
 * drawing. Watching eleven hairlines of ruling draw themselves is noise, not
 * reassurance; four strokes say "notebook, bound, marked" and stop.
 *
 * ── Why there are no dasharray numbers here ────────────────────────────────
 *
 * ── Why the colours are `var()` and not Tailwind classes ───────────────────
 *
 * The previous version set `text-ink` / `text-accent` and painted with
 * `currentColor`. Driving that from the geometry module would mean building the
 * class name — `text-${stroke}` — and Tailwind's scanner only sees class names
 * that appear literally in the source, so those two utilities would silently
 * stop being generated and the mark would render in whatever colour it
 * inherited. `var(--ink)` needs no scanner and tracks the same token.
 *
 * stroke-dash* calculation, so `stroke-dasharray: 1; stroke-dashoffset: 1` is
 * "fully undrawn" for any path regardless of its real length. The previous
 * version hardcoded 36, 24 and 42 — three measurements of three specific paths,
 * copied into two files, silently wrong the moment a curve moved. Nothing here
 * needs to know how long anything is.
 */

export function Mark({
  size = 24,
  animated = false,
  className,
}: {
  size?: number
  animated?: boolean
  className?: string
}) {
  return (
    <svg
      viewBox={MARK_VIEW_BOX_TIGHT}
      width={size}
      height={(size * 45) / 60}
      fill="none"
      className={className}
      // Animated: this IS the content (a screen reader user needs to know the
      // page is still working), so it is a named image, not decoration.
      // Static: it is brand furniture beside a heading that already says
      // everything, so it stays out of the accessibility tree per §4.1/§8.
      role={animated ? "img" : undefined}
      aria-label={animated ? "Lemely is still loading" : undefined}
      aria-hidden={animated ? undefined : "true"}
    >
      <g transform={MARK_TILT}>
        {MARK_OUTLINE.map(({ step, paths, stroke, width, mirrored }) => {
          const drawn = paths.map((d) => (
            <path
              key={d}
              d={d}
              pathLength="1"
              className={animated ? `lm-draw-${step}` : undefined}
              stroke={`var(--${stroke})`}
              strokeWidth={width}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))
          return mirrored ? (
            <g key={step} transform={MARK_MIRROR}>
              {drawn}
            </g>
          ) : (
            <g key={step}>{drawn}</g>
          )
        })}
      </g>
    </svg>
  )
}
