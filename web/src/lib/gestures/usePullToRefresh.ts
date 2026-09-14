import { useEffect, useRef, useState, type RefObject } from "react"
import { pullStartAllowed, pullState, usesOwnScrollTop } from "./pullMath"
import { useDragGesture } from "./useDragGesture"
import { EDGE_ZONE_PX } from "@/lib/nav/edgeSwipeBack"

/*
 * Task 5 (B4a) · pull-to-refresh built on `useDragGesture` (Task 4), the
 * same shared one-finger-drag primitive `EdgeSwipeBack` and `NavDrawer`'s
 * drag-dismiss use. `axis: "y"` gets `useDragGesture`'s own imperative
 * `translateY(dy)` on `ref` itself for free while dragging (its default
 * `transformTarget` is `ref`), which is what visibly pushes the screen's
 * content down as the user pulls. `--lm-pull-progress`, set here on the same
 * element, is the hook's own signal to `PullIndicator` (typically an
 * absolutely-positioned sibling revealed as the content moves down) — a CSS
 * custom property rather than a second ref, since the hook's signature below
 * takes only the one ref.
 *
 * That ref must be an element *inside* the screen, never
 * `document.documentElement`. A transformed root becomes the containing
 * block for every `position: fixed` descendant, so pulling on a screen wired
 * that way dragged `BottomNav`, the modal scrim and the nav drawer down with
 * it — and the root is also where `EdgeSwipeBack` listens, which put two
 * gestures on one element writing one `style.transform`. The scroll-top and
 * `overscroll-behavior` questions are answered against the real scroller
 * (`usesOwnScrollTop`), which for a plain content wrapper is still the
 * window.
 *
 * `onRefresh` fires once per pull: `useDragGesture`'s own `commitThreshold`
 * (10px, dominant-axis) recognises the gesture as a real vertical drag long
 * before `threshold` (72px default) — that's what makes it "release", not
 * "should call `onRefresh`". `pullState` (kept pure, `pullMath.ts`) is the
 * arbiter of the latter; `armedRef` carries its answer from the last
 * `onProgress` tick to `onCommit`.
 */

export interface UsePullToRefreshOptions {
  onRefresh: () => Promise<unknown>
  /** Downward pull distance, in CSS pixels, that arms a refresh on release.
   * Default 72. */
  threshold?: number
  /** Default true. `false` detaches the gesture entirely, same as
   * `useDragGesture`'s own `enabled`. */
  enabled?: boolean
}

export interface UsePullToRefreshResult {
  pulling: boolean
  refreshing: boolean
}

/** Which element's `scrollTop` answers "are we at the top?" for `el` — `el`
 * itself if it really is a scroller, otherwise the window. Reading
 * `overflowY` forces a style recalculation, so this is resolved once when a
 * drag starts and reused for the rest of it, never per `pointermove`. */
function scrollSourceOf(el: HTMLElement): HTMLElement | null {
  return usesOwnScrollTop(getComputedStyle(el).overflowY, el.scrollHeight, el.clientHeight) ? el : null
}

function isAtScrollTop(source: HTMLElement | null): boolean {
  return source === null ? window.scrollY === 0 : source.scrollTop === 0
}

export function usePullToRefresh(
  ref: RefObject<HTMLElement | null>,
  options: UsePullToRefreshOptions,
): UsePullToRefreshResult {
  const { onRefresh, threshold = 72, enabled = true } = options
  const onRefreshRef = useRef(onRefresh)
  onRefreshRef.current = onRefresh
  const armedRef = useRef(false)
  const scrollSourceRef = useRef<HTMLElement | null>(null)
  const [pulling, setPulling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  // `overscroll-behavior-y: contain` suppresses the browser's *own* pull-to-
  // refresh, so it has to land on whatever actually scrolls — the document
  // root when the surface is a plain content wrapper (the usual case since
  // the surface stopped being `documentElement` itself), the surface when it
  // is a real scroller.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const scroller = scrollSourceOf(el) ?? document.documentElement
    const previous = scroller.style.overscrollBehaviorY
    scroller.style.overscrollBehaviorY = "contain"
    return () => {
      scroller.style.overscrollBehaviorY = previous
    }
  }, [ref])

  function resetIndicator() {
    setPulling(false)
    armedRef.current = false
    ref.current?.style.setProperty("--lm-pull-progress", "0")
  }

  useDragGesture(ref, {
    axis: "y",
    enabled: enabled && !refreshing,
    // Downward only. An unsigned `translateY(dy)` meant an upward drag at the
    // scroll top dragged the whole screen up instead of leaving the browser
    // to do nothing — and no `touchAction` here on purpose: this surface must
    // keep panning vertically or the page stops scrolling through it.
    transformClamp: "positive",
    startFilter: (event) => {
      const el = ref.current
      if (el === null) return false
      scrollSourceRef.current = scrollSourceOf(el)
      if (!isAtScrollTop(scrollSourceRef.current)) return false
      // `EdgeSwipeBack` listens on `document`, so this pointerdown reaches it
      // too. Ceding the two edge strips keeps the zones disjoint instead of
      // letting both gestures capture the same pointer (C3).
      return pullStartAllowed(event.clientX, window.innerWidth, EDGE_ZONE_PX)
    },
    onProgress: (_dx, dy) => {
      const el = ref.current
      if (!el) return
      const { progress, armed } = pullState(dy, threshold, isAtScrollTop(scrollSourceRef.current))
      armedRef.current = armed
      el.style.setProperty("--lm-pull-progress", String(progress))
      setPulling(progress > 0)
    },
    onCommit: () => {
      const shouldRefresh = armedRef.current
      resetIndicator()
      if (!shouldRefresh) return
      setRefreshing(true)
      onRefreshRef.current().finally(() => {
        setRefreshing(false)
      })
    },
    onCancel: () => {
      resetIndicator()
    },
  })

  return { pulling, refreshing }
}
