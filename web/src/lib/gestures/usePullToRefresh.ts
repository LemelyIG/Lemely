import { useEffect, useRef, useState, type RefObject } from "react"
import { pullStartAllowed, pullState, usesOwnScrollTop } from "./pullMath"
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
    startFilter: (event) => {
      // Issue #246/#247: a plain tap on a button or `<Link>` at the scroll
      // top used to arm this gesture exactly like a real drag would —
      // `useDragGesture`'s `onPointerDown` calls `setPointerCapture`
      // regardless of whether the pointer ever moves, and a captured
      // pointer retargets the tap's `click` away from whatever was under
      // it. That silently killed "Mark as read"/"Show more" on
      // Announcements, "Mark as read"/"Open"/"Mark all as read" on
      // Notifications, and `<Link>` navigation on Overview's subject rows
      // (a swallowed click stops a router `<Link>` exactly as dead as it
      // stops a mutation button) — confirmed broken on all three screens,
      // not just structurally similar.
      //
      // `startFilter`'s own doc comment already names the fix: returning
      // `false` here is defined as "lets the event fall through ... instead
      // of starting a drag", not "starts a drag but skips it if the pointer
      // never moves". So a press that begins on a control and is then
      // dragged does NOT become a pull, even past `threshold` — it falls
      // through to whatever the control's own touch behaviour is (a native
      // scroll, most likely), same as it always has for every other
      // `startFilter` exemption (the edge-swipe strip, the scroll-top
      // check).
      //
      // Considered and rejected, twice, on two different (wrong) reasons
      // before landing on the real one — recorded so a third pass does not
      // repeat the exercise: making a press-then-drag on a control promote
      // into a pull, by having `useDragGesture` track the pointer on any
      // target but defer `setPointerCapture` until real movement is
      // confirmed, instead of hard-rejecting interactive targets in
      // `startFilter`.
      //
      // The reason this stays hard-rejected: `setPointerCapture` at
      // `pointerdown` is what guarantees `endDrag` ever runs at all.
      // `useDragGesture` attaches `pointermove`/`pointerup`/`pointercancel`
      // directly on the surface element, and today capture means every one
      // of those events retargets to it regardless of where the pointer
      // physically travels — off the element, off the screen, anywhere.
      // Defer capture until `commitThreshold` is crossed and, during that
      // pre-commit window, those listeners only fire while the pointer is
      // still hit-testing inside the surface's own subtree: a fast enough
      // pre-threshold movement — `commitThreshold` defaults to 10px here
      // (this hook does not override it), and other `useDragGesture`
      // consumers set it far higher still (`QuizTaker`'s is 60px, the nav
      // drawer's is ~40% of its own panel width) — can carry the pointer
      // out from under the surface (or under an intervening element)
      // before capture would ever be requested, so `pointerup` fires
      // somewhere the surface's own listener never sees.
      // The result: `stateRef.current` never clears, the move/up/cancel
      // listeners stay attached, and the drag never gets to `springBack`
      // whatever it already wrote to `style.transform`. That is the exact
      // failure class `useDragGesture.ts`'s own `H5` cleanup effect exists
      // to prevent for a *different* trigger (a stale `enabled` toggle
      // mid-drag) — deferred capture would reopen the same class of bug
      // through a different door. Hard-rejecting here costs one
      // interaction — a pull cannot be initiated by pressing directly on a
      // control — in exchange for keeping that guarantee intact for every
      // `useDragGesture` consumer, not just this one.
      const target = event.target
      if (target instanceof Element && target.closest(GESTURE_INTERACTIVE_SELECTOR) !== null) return false
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
