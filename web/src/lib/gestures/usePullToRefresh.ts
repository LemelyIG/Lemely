import { useEffect, useRef, useState, type RefObject } from "react"
import { pullStartDecision, pullState, usesOwnScrollTop } from "./pullMath"
import { useDragGesture } from "./useDragGesture"
import { GESTURE_INTERACTIVE_SELECTOR } from "./interactiveSelector"
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
    // Issue #246/#247: a plain tap on a button or `<Link>` at the scroll top
    // used to arm this gesture exactly like a real drag would —
    // `useDragGesture`'s `onPointerDown` calls `setPointerCapture`
    // regardless of whether the pointer ever moves, and a captured pointer
    // retargets the tap's `click` away from whatever was under it. That
    // silently killed "Mark as read"/"Show more" on Announcements, "Mark as
    // read"/"Open"/"Mark all as read" on Notifications, and `<Link>`
    // navigation on Overview's subject rows — confirmed broken on all three
    // screens, not assumed from matching structure.
    //
    // A tap on an interactive control is now refused outright
    // (`pullStartDecision`'s `interactive` check, `pullMath.ts`), and that
    // is correct on its own terms, not a limitation accepted to route
    // around a cost. `startFilter`'s own doc comment already enumerates
    // this exact case among what should fall through rather than start a
    // drag: "scroll, native selection, a nested interactive control". A
    // control owns its own press; this fix makes the gesture honour a
    // contract it already claimed, not a new restriction on it.
    //
    // Promoting a press-then-drag on a control into a pull — considered, and
    // would not even work reliably: `shouldCommitDrag` (`dragMath.ts`) also
    // requires the dominant axis to outrun the other by more than 2x, so a
    // hesitant pull that wanders sideways as it goes down would not commit
    // even if capture were deferred to allow it. A fix that works
    // *sometimes* is indistinguishable from broken, which is what #246 was.
    //
    // There is no user need traded away here to note as a cost: both
    // screens this reaches render a heading above the content a student
    // would tap, a pull from there still refreshes normally, and pulling by
    // pressing directly on a button was never how anyone reaches for this
    // gesture.
    //
    // Kept as a secondary note so a future pass does not re-propose
    // deferring capture as a *correctness* improvement: it would not be
    // one. Capture at `pointerdown` is what guarantees `pointerup`/
    // `pointercancel` ever reach the surface, wherever the pointer travels.
    // Deferred, those listeners only fire while the pointer is still inside
    // the surface's own subtree — `pointercancel` included, since the
    // browser dispatches it to whatever is currently under the pointer, not
    // to whoever asked for it. A release outside that subtree before
    // capture ever happens means `endDrag` never runs: `stateRef.current`
    // stays non-null, and `onPointerDown`'s own guard
    // (`if (stateRef.current !== null) return`) then ignores every later
    // press on that surface, permanently. `useDragGesture.ts`'s own `H5`
    // fix already documents this exact class of bug happening once, for a
    // different trigger (a stale `enabled` toggle mid-drag left a card
    // "permanently offset ... still holding pointer capture and swallowing
    // every tap that landed on it").
    startFilter: (event) => {
      const target = event.target
      const interactive = target instanceof Element && target.closest(GESTURE_INTERACTIVE_SELECTOR) !== null
      const el = ref.current
      if (el === null) return false
      scrollSourceRef.current = scrollSourceOf(el)
      // `EdgeSwipeBack` listens on `document`, so this pointerdown reaches it
      // too. Ceding the two edge strips keeps the zones disjoint instead of
      // letting both gestures capture the same pointer (C3).
      return pullStartDecision({
        interactive,
        atTop: isAtScrollTop(scrollSourceRef.current),
        clientX: event.clientX,
        viewportWidth: window.innerWidth,
        edgeZonePx: EDGE_ZONE_PX,
      })
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
