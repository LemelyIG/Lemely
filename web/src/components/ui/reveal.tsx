/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { prefersReducedMotion } from "@/lib/celebration"

/**
 * Scroll-entry reveal: a gentle fade-up as the element comes into view, with
 * an optional stagger delay.
 *
 * DESIGN.md §9 and REDESIGN-MISSION §4 both specify this as the product's
 * baseline "invisible motion" — 600ms fade-up scroll entries with stagger —
 * and until now **nothing in the product implemented it**. `lm-screen` fades a
 * whole route in once on mount, which is a different thing: it fires for
 * content below the fold that nobody has scrolled to yet, so by the time a
 * reader arrives the animation has long since finished and the page is static.
 * That is fine for an app screen, which is one viewport of content. It is not
 * fine for a six-section marketing page, which is the surface the spec wrote
 * this for.
 *
 * Three rules from §3.2 item 14, all load-bearing:
 *
 * 1. **IntersectionObserver, never a scroll listener.** A scroll handler runs
 *    on the main thread at every frame of every scroll; the observer runs when
 *    the browser has already computed intersection for its own reasons.
 * 2. **`transform` and `opacity` only.** Nothing here touches width, height,
 *    top or margin, so no frame of this animation can trigger layout.
 * 3. **`prefers-reduced-motion` has a real path, read in JS.** Not a media
 *    query that skips the transition while still starting from `opacity: 0` —
 *    that is how a reduced-motion reader ends up on a permanently invisible
 *    page if the observer never fires. When motion is off, the element mounts
 *    visible and no observer is created at all.
 *
 * `once: true` by default, and deliberately: an element that re-fades every
 * time it re-enters the viewport turns an ordinary scroll back up the page
 * into a light show. Nothing in this product needs that.
 */
export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode
  /** Stagger, in milliseconds. Keep siblings under ~300ms total. */
  delay?: number
  className?: string
  as?: "div" | "section" | "li"
}) {
  /*
   * Read once, at mount, rather than on every render: the value cannot change
   * mid-animation in any way that would leave a half-revealed element, and
   * reading it lazily here means a reduced-motion reader never gets the
   * `opacity-0` starting state in their markup at all.
   */
  const [reduced] = useState(prefersReducedMotion)
  const [shown, setShown] = useState(reduced)
  const ref = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (reduced || shown) return
    const node = ref.current
    /*
     * No node, or no IntersectionObserver in this browser: show the content.
     * The failure mode to avoid is the opposite one — leaving `opacity-0` in
     * place because the mechanism that would have removed it is missing, which
     * renders a blank page rather than an unanimated one.
     */
    if (!node || typeof IntersectionObserver === "undefined") {
      setShown(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true)
          observer.disconnect()
        }
      },
      // A little margin off the bottom so the entry starts just before the
      // element is strictly on screen, and it reads as arriving rather than
      // as popping in late.
      { rootMargin: "0px 0px -8% 0px", threshold: 0.05 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [reduced, shown])

  return (
    <Tag
      ref={ref as React.Ref<never>}
      className={cn(
        "motion-safe:transition-[opacity,transform]",
        // `--dur-slow` is 600ms, which is the figure §4 names for a scroll
        // entry. The `--dur-*` tokens live in `:root` and not in `@theme`, so
        // a named `duration-slow` utility does not exist and emits nothing —
        // D4.6's finding. The arbitrary-value form reads the variable directly
        // and is the documented way to use these.
        "motion-safe:duration-[var(--dur-slow)] motion-safe:ease-out-soft",
        shown ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0",
        className,
      )}
      /*
       * The delay stays applied after `shown` flips, and that is the whole
       * point: clearing it at the moment the transition starts would cancel
       * the stagger it exists to create, leaving every sibling to arrive on
       * the same frame. `once: true` means there is no later transition for
       * the lingering delay to affect.
       */
      style={reduced ? undefined : { transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  )
}
