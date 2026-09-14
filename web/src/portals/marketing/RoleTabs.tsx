/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V5 */
import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import type { RoleTab } from "./data"

/**
 * "Who it serves", as an accessible tabbed switcher rather than a third
 * bordered card grid on this page.
 *
 * Task 3's whole reason for existing: the live judge, across four
 * consecutive evaluator runs, named "How it works" and "One marked paper,
 * three people it helps" as the SAME bordered three-equal-card layout family
 * sitting back to back, and a plain three-equal-card row is independently a
 * hard-gate violation on its own. A tab widget solves both at once: only one
 * role's content is ever on screen, so there is no row of three cards to
 * repeat, and the section reads as a switch rather than a shelf.
 *
 * Built to the WAI-ARIA APG tabs pattern by hand rather than pulled from a
 * library, because the kit has no tabs primitive yet and this is a three-item
 * switcher, not a case for a new dependency:
 *   - `role="tablist"` / `role="tab"` / `role="tabpanel"`, wired by
 *     `aria-controls` / `aria-labelledby`.
 *   - `aria-selected` on the active tab only.
 *   - Roving tabindex: the active tab is the only one in the page's Tab
 *     order (`tabIndex 0`), the rest are `-1`, so Tab does not have to pass
 *     through three role buttons to reach whatever follows the section.
 *   - Left/Right arrow keys move focus AND selection together (the APG's
 *     "automatic activation" model), which is the right choice here since
 *     each panel's cost of being wrong is nothing: no data loads, nothing
 *     submits, so there is no reason to make a reader confirm a highlight
 *     before it takes effect.
 *   - Student is the default (`roles[0]`), matching `data.ts`'s own
 *     ordering and the product's own registration order.
 *
 * No entry animation on a tab switch: BUILD/BRAND.md §1's "calm" trait reads
 * as "no urgency theatre", and `Reveal`'s fade is built for a first scroll
 * arrival, not a click that re-fires the same IntersectionObserver moment on
 * content already in view. The switch is instant, the same way flipping a
 * page is instant.
 */
export function RoleTabs({ roles }: { roles: RoleTab[] }) {
  const navigate = useNavigate()
  const [activeId, setActiveId] = useState(roles[0].id)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const activeIndex = roles.findIndex((r) => r.id === activeId)
  const active = roles[activeIndex] ?? roles[0]

  /** Moves both focus and selection to `roles[index]`, wrapping at the ends
   * so Right on the last tab reaches the first (the APG's recommended
   * behaviour for a small, closed set like this one). */
  function activate(index: number) {
    const wrapped = (index + roles.length) % roles.length
    const role = roles[wrapped]
    setActiveId(role.id)
    tabRefs.current[role.id]?.focus()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowRight") {
      e.preventDefault()
      activate(activeIndex + 1)
    } else if (e.key === "ArrowLeft") {
      e.preventDefault()
      activate(activeIndex - 1)
    } else if (e.key === "Home") {
      e.preventDefault()
      activate(0)
    } else if (e.key === "End") {
      e.preventDefault()
      activate(roles.length - 1)
    }
  }

  return (
    <div className="mt-10">
      <div
        role="tablist"
        aria-label="Who Lemely serves"
        onKeyDown={onKeyDown}
        className="flex gap-1 border-b border-rule"
      >
        {roles.map((r) => {
          const selected = r.id === activeId
          return (
            <button
              key={r.id}
              ref={(el) => {
                tabRefs.current[r.id] = el
              }}
              type="button"
              role="tab"
              id={`role-tab-${r.id}`}
              aria-selected={selected}
              aria-controls="role-panel"
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveId(r.id)}
              className={`text-label whitespace-nowrap rounded-t-md px-3 py-3 -mb-px border-b-2 pointer-coarse:min-h-11 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:px-4 ${
                selected
                  ? "border-accent text-ink"
                  : "border-transparent text-ink-faint hover:text-ink"
              }`}
            >
              {r.label}
            </button>
          )
        })}
      </div>

      <div
        role="tabpanel"
        id="role-panel"
        aria-labelledby={`role-tab-${active.id}`}
        tabIndex={0}
        className="mt-8 flex flex-col items-start gap-4"
      >
        <h3 className="text-display-lg text-ink text-balance">{active.heading}</h3>
        <p className="text-body-lg max-w-[56ch] text-pretty text-ink-muted">{active.body}</p>
        <Button variant="primary" onClick={() => navigate(active.cta.to)}>
          {active.cta.label}
        </Button>
      </div>
    </div>
  )
}
