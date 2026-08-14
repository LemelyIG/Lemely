/* Hallmark · pre-emit critique: P4 H4 E5 S5 R4 V3 */
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * P3.1 (DECISION D1.5) · Breadcrumb trail with a back affordance.
 *
 * The audit's finding was that the teacher and parent portals have no
 * consistent way back. That is worse in the teacher portal than the sentence
 * makes it sound, because several of its screens are only reachable by drilling
 * in — `/teacher/students/:id` is reached from a class roster, and
 * `/teacher/review/:itemId` from the review queue — and neither drilled-into
 * screen rendered any route back to where the drill started. The browser back
 * button worked, which is exactly why this went unnoticed on a laptop and would
 * not survive a phone, where the same gesture is inconsistent across browsers
 * and absent from an installed PWA. The parent portal has the same hole with a
 * sharper edge: PRODUCT.md's parent is defined as having "no interest in
 * learning an interface".
 *
 * Deliberately a trail rather than a lone "< Back" button. Back says only that
 * there is a previous thing; a trail says where you are, which is the question
 * a drilled-in screen actually raises. On phones the trail collapses to its
 * last link so it stays one line and one tap (see `collapse` below) — the same
 * affordance, not a different one.
 *
 * Honesty rule: crumb labels here name the *kind* of thing ("This class",
 * "This student") rather than interpolating an id. A UUID in a breadcrumb is
 * noise, and fetching the display name to put there would make a navigation
 * chrome depend on a request that can fail or lag — the trail must render
 * instantly and correctly on first paint or it is not a wayfinding aid.
 */

export interface Crumb {
  label: string
  /** Omitted on the final crumb: the page you are already on is not a link. */
  to?: string
}

export interface BreadcrumbsProps {
  items: Crumb[]
  /**
   * When true (the default), every crumb but the last is hidden below `sm`
   * and only the nearest ancestor shows, prefixed with a back caret. Set
   * false on surfaces with room to spare at every width.
   */
  collapse?: boolean
  className?: string
}

export function Breadcrumbs({ items, collapse = true, className }: BreadcrumbsProps) {
  if (items.length === 0) return null

  // The nearest ancestor with a link is what the collapsed mobile form shows.
  // Searching from the end rather than taking `items[items.length - 2]`
  // because a caller may pass an unlinked intermediate crumb (a grouping label
  // with no route of its own), and pointing "back" at something unclickable
  // would render a caret that does nothing.
  const parent = [...items]
    .slice(0, -1)
    .reverse()
    .find((item) => item.to !== undefined)

  // Collapse only happens when there is somewhere to collapse *to*. A
  // single-crumb trail, or one whose ancestors are all unlinked, keeps its
  // full form at every width — hiding it would leave an empty <nav>.
  const collapsed = collapse && parent !== undefined

  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      {/* `text-body-sm`, not `text-metadata`. The existing student header crumb
          is mono, and DESIGN.md §11 scopes the mono `data-sm` rung to "paper
          codes, IDs, timestamps, metadata" — crumb labels are none of those,
          they are words a reader reads. Phase 4 migrates the student header to
          match this rather than the reverse. */}
      <ol className="flex min-w-0 items-center gap-1.5 text-body-sm text-ink-muted">
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          return (
            <li
              key={`${item.label}-${index}`}
              className={cn(
                "flex min-w-0 items-center gap-1.5",
                // Collapsed form: the whole trail is hidden below `sm` and
                // replaced wholesale by the single back link at the end of
                // this list. Hiding every crumb including the current one is
                // deliberate — the page's own <h1> already says where you are,
                // so repeating it in the trail spends a scarce line of phone
                // width on the one fact the screen cannot fail to convey.
                collapsed && "hidden sm:flex",
              )}
            >
              {index > 0 ? (
                // `rtl:-scale-x-100` — this glyph points along the reading
                // direction, so it is one of the direction-dependent icons
                // P3.4 requires be flagged. It must mirror under `dir="rtl"`.
                //
                // Visible at every width, not `hidden sm:block`. The separator
                // only needs hiding when the trail itself is hidden, and in
                // collapsed mode the whole <li> already carries `hidden
                // sm:flex` — so pinning the caret to `sm` as well did nothing
                // there and, with `collapse={false}`, stripped the separators
                // out on a phone and left the crumbs running together as
                // "Overview Classes This class Analytics".
                <CaretRight
                  size={12}
                  aria-hidden="true"
                  className="shrink-0 text-rule rtl:-scale-x-100"
                />
              ) : null}
              {/* Only the final crumb truncates. `truncate` on every crumb
                  shares the squeeze equally, so a narrow container turns the
                  whole trail into "Overvi… Clas… This cl… Analy…", which
                  communicates less than no trail at all. Ancestors are short,
                  controlled labels taken from the nav list, so `nowrap` is
                  safe for them; the current page's label is the only one that
                  can be long, and it is the one a reader can most afford to
                  see clipped because the page heading repeats it. */}
              {item.to && !isLast ? (
                <Link
                  to={item.to}
                  className={cn(
                    "whitespace-nowrap rounded-sm transition-colors hover:text-ink",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    /* §6.1's 44px floor; a crumb measured 65x20. The `<li>` is
                       a flex container, so this link is a flex item and its
                       computed display is `block` rather than `inline` — which
                       is why `min-block-size` reaches it at all, and why it
                       also needs its own centring, or the label would sit at
                       the top of the taller box. Below `sm` the trail collapses
                       to a single back link, so on a phone this raises exactly
                       the one control a reader reaches for. */
                    "pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11",
                  )}
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  className={cn(
                    isLast ? "truncate text-ink" : "whitespace-nowrap",
                  )}
                  aria-current={isLast ? "page" : undefined}
                >
                  {item.label}
                </span>
              )}
            </li>
          )
        })}

        {/* Mobile-only back link. A separate node rather than restyling the
            parent crumb above, because it needs the caret on the leading side
            and a 44px touch target, and expressing both as overrides on the
            desktop crumb produced a control that was neither at the boundary.
            Hidden from assistive tech via the wrapper being `sm:hidden` and
            the desktop trail carrying the real semantics — a screen reader
            gets one trail, not two, at every width. */}
        {collapsed ? (
          <li className="flex min-w-0 items-center sm:hidden">
            <Link
              to={parent.to!}
              className={cn(
                "-ms-2 flex min-h-11 min-w-0 items-center gap-1 px-2 py-1 text-ink-muted transition-colors",
                "hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              )}
            >
              {/* Points back against the reading direction, so it mirrors too. */}
              <CaretRight
                size={12}
                aria-hidden="true"
                className="shrink-0 -scale-x-100 rtl:scale-x-100"
              />
              <span className="truncate">{parent.label}</span>
            </Link>
          </li>
        ) : null}
      </ol>
    </nav>
  )
}
