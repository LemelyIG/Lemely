import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { usePullToRefresh } from "@/lib/gestures/usePullToRefresh"
import { nativeHaptic } from "@/lib/haptics"
import { useNativeFrame } from "@/lib/useNativeFrame"

/** The preview's arm distance on both platforms (`--pf-ptr-threshold`); the
 * same number as `--native-ptr-threshold`, pinned by shellPullToRefresh.test.ts. */
export const PULL_THRESHOLD_PX = 64

/** The pull's visual ceiling (`--native-ptr-max`, preview `PTR_MAX`). */
export const PULL_MAX_PX = 140

/** How long the settle transition runs (`--dur-slow`, 350ms), before `data-ptr` clears. Pinned by shellPullToRefresh.test.ts. */
export const SETTLE_MS = 350

const SPOKES = [0, 1, 2, 3, 4, 5, 6, 7]

/**
 * Finger distance to drawn distance. 1:1 up to the arm threshold, so the
 * indicator reads "armed" exactly when the release would refresh, then a
 * rubber band that eases toward `max`.
 */
export function pullDistance(dy: number, threshold = PULL_THRESHOLD_PX, max = PULL_MAX_PX): number {
  if (dy <= 0) return 0
  if (dy <= threshold) return dy
  const room = max - threshold
  return threshold + room * (1 - Math.exp(-(dy - threshold) / (room * 1.6)))
}

/** Native frame D6: one pull-to-refresh on every root page of both portals.
 * It refetches whatever the page is showing (active queries), so no screen
 * has to wire its own. iOS drags the content down with the finger and shows
 * an 8-spoke activity indicator in the gap; Android keeps the content still
 * and slides an M3 disc with a growing arc over it. The look lives in
 * index.css (`.lm-ptr*`); this component only feeds it `--pf-pull`,
 * `--pf-pull-p` and `data-ptr`. */
export function ShellPullToRefresh({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const surface = useRef<HTMLDivElement>(null)
  // The drag hook moves one element by the raw finger distance. This one is
  // hidden, so that movement is invisible and the CSS moves what it wants.
  const sink = useRef<HTMLSpanElement>(null)
  // The pull's custom properties are written on these two only (see index.css:
  // `--pf-pull` does not inherit), never on the surface, so a pull frame does not
  // restyle the page inside the content.
  const gap = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const armed = useRef(false)
  const cleared = useRef(false)
  const wasActive = useRef(false)
  const [settling, setSettling] = useState(false)
  const { platform } = useNativeFrame()
  const queryClient = useQueryClient()

  const { pulling, refreshing } = usePullToRefresh(surface, {
    enabled,
    threshold: PULL_THRESHOLD_PX,
    transformTarget: sink,
    onPull: (dy) => {
      const gapEl = gap.current
      const contentEl = content.current
      if (!gapEl || !contentEl) return
      if (dy <= 0) {
        armed.current = false
        cleared.current = false
        gapEl.style.removeProperty("--pf-pull")
        gapEl.style.removeProperty("--pf-pull-p")
        contentEl.style.removeProperty("--pf-pull")
        return
      }
      // The first frame of a pull drops any selection the press began, so the copy under the finger never stays highlighted.
      if (!cleared.current) {
        cleared.current = true
        window.getSelection()?.removeAllRanges()
      }
      const pull = pullDistance(dy)
      gapEl.style.setProperty("--pf-pull", `${pull}px`)
      gapEl.style.setProperty("--pf-pull-p", String(Math.min(1, pull / PULL_THRESHOLD_PX)))
      contentEl.style.setProperty("--pf-pull", `${pull}px`)
      const over = dy >= PULL_THRESHOLD_PX
      if (over && !armed.current) nativeHaptic("tap")
      armed.current = over
    },
    onRefresh: () => queryClient.refetchQueries({ type: "active" }),
  })

  const active = pulling || refreshing
  useEffect(() => {
    if (active) {
      wasActive.current = true
      return
    }
    if (!wasActive.current) return
    wasActive.current = false
    setSettling(true)
    const timer = setTimeout(() => setSettling(false), SETTLE_MS)
    return () => clearTimeout(timer)
  }, [active])

  // One tree whether or not the pull is enabled, so crossing the phone
  // breakpoint never remounts the page; disabled, every wrapper is `contents`.
  const phase = refreshing ? "refreshing" : pulling ? "pulling" : settling ? "settling" : undefined
  return (
    <div ref={surface} data-ptr={phase} className={enabled ? "lm-ptr overscroll-y-contain" : "contents"}>
      {enabled ? (
        <>
          <div ref={gap} className="lm-ptr-gap" aria-hidden="true">
            {platform === "ios" ? (
              <span className="lm-ptr-ios">
                {SPOKES.map((i) => (
                  <i key={i} style={{ "--i": i } as CSSProperties} />
                ))}
              </span>
            ) : (
              <span className="lm-ptr-md">
                <svg viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="8.5" />
                </svg>
              </span>
            )}
          </div>
          <span role="status" className="sr-only">
            {refreshing ? "Refreshing" : ""}
          </span>
        </>
      ) : null}
      <div ref={content} className={enabled ? "lm-ptr-content" : "contents"}>{children}</div>
      <span ref={sink} hidden />
    </div>
  )
}
