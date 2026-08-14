import { useEffect, useState } from "react"

/*
 * "Has this element come near the viewport yet?" — latches true and stays true.
 *
 * ── Why this exists (P6.3) ──────────────────────────────────────────────────
 *
 * REDESIGN-MISSION §5 Phase 6.3 asks for "lazy images". The product has exactly
 * one content image worth the name — the teacher grading console's per-paper
 * scan thumbnail — and `loading="lazy"` on it would have done **nothing**,
 * because the bytes are not fetched by the image element. `useScanPreview`
 * calls `fetchBlobUrl("/papers/{id}/preview")` and hands the resulting
 * `blob:` object URL to `<img src>`, so by the time the element exists the
 * download has already happened. A `blob:` URL is local; there is no request
 * left for the browser to defer.
 *
 * That matters more than a normal lazy-loading miss, because the endpoint is
 * not a static file. `GET /papers/{id}/preview` opens the stored scan with
 * PyMuPDF and renders page 1 to a PNG on demand. `GET /papers` is unpaginated
 * and returns every tracked paper, and every card mounts its own hook, so
 * opening the console rendered *every* scan the school has ever uploaded, at
 * once, to draw a strip of 64px-tall thumbnails most of which are below the
 * fold. The endpoint's own comment shows the cost was known and answered by
 * shrinking the image ("every step up costs a bigger payload on every card in
 * the grid at once") rather than by not asking for it.
 *
 * So the deferral has to happen where the request is actually made, which is
 * this hook's job: gate the fetch on the card approaching the viewport.
 *
 * ── Why not fold `Reveal` into this ────────────────────────────────────────
 *
 * `components/ui/reveal.tsx` also runs an IntersectionObserver and this looks
 * like the same mechanism. It is not the same *policy*. `Reveal` fires when an
 * element is genuinely on screen and slightly past it (`-8%` bottom margin), so
 * the animation reads as arriving rather than as already over; it is also
 * short-circuited by `prefers-reduced-motion`, which is load-bearing there and
 * meaningless here — a reader who wants less motion still wants their
 * thumbnails. This one deliberately fires *early* (see `DEFAULT_ROOT_MARGIN`)
 * and never consults the motion preference. Merging them would mean one call
 * site silently choosing the other's timing. `Reveal` is Phase 5 code with
 * three passing motion gates on it and is deliberately left alone.
 */

/** Fire a screen-height ahead of the viewport.
 *
 * The point of a lazy fetch is that the image is *there* when the reader
 * arrives, not that they watch it load. A render + download that starts when
 * the card is already on screen trades an over-eager grid for a visibly empty
 * one, which on this screen is worse: an empty thumbnail is the same thing the
 * card shows for a scan that failed to render.
 */
const DEFAULT_ROOT_MARGIN = "100% 0px"

export interface InViewOnceOptions {
  rootMargin?: string
  threshold?: number
}

/**
 * @param node The element to watch. Pass state from a callback ref, not a
 *   `useRef` — a ref object's `.current` mutation does not re-run the effect,
 *   so a card that mounts its node after the first render would never be
 *   observed.
 */
export function useInViewOnce(node: Element | null, options: InViewOnceOptions = {}): boolean {
  const { rootMargin = DEFAULT_ROOT_MARGIN, threshold = 0 } = options
  const [seen, setSeen] = useState(false)

  useEffect(() => {
    if (seen) return
    /*
     * No node yet, or a browser with no IntersectionObserver: report visible.
     * Fails *open*, the same way `Reveal` does and for the same reason — the
     * bad outcome is not an extra fetch, it is a grid of permanently blank
     * thumbnails because the mechanism that would have released them is
     * missing. This restores exactly the pre-P6.3 behaviour on such a browser.
     */
    if (!node || typeof IntersectionObserver === "undefined") {
      if (!node) return
      setSeen(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true)
          observer.disconnect()
        }
      },
      { rootMargin, threshold },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [node, seen, rootMargin, threshold])

  return seen
}
