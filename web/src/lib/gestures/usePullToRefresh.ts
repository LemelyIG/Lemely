import { useEffect, useRef, useState, type RefObject } from "react"
import { pullState } from "./pullMath"
import { useDragGesture } from "./useDragGesture"

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
 * takes only the one scroll-container ref.
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

function isAtScrollTop(el: HTMLElement): boolean {
  if (el === document.documentElement || el === document.body) return window.scrollY === 0
  return el.scrollTop === 0
}

export function usePullToRefresh(
  ref: RefObject<HTMLElement | null>,
  options: UsePullToRefreshOptions,
): UsePullToRefreshResult {
  const { onRefresh, threshold = 72, enabled = true } = options
  const onRefreshRef = useRef(onRefresh)
  onRefreshRef.current = onRefresh
  const armedRef = useRef(false)
  const [pulling, setPulling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const previous = el.style.overscrollBehaviorY
    el.style.overscrollBehaviorY = "contain"
    return () => {
      el.style.overscrollBehaviorY = previous
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
    startFilter: () => {
      const el = ref.current
      return el !== null && isAtScrollTop(el)
    },
    onProgress: (_dx, dy) => {
      const el = ref.current
      if (!el) return
      const { progress, armed } = pullState(dy, threshold, isAtScrollTop(el))
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
