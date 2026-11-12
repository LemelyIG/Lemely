import { useEffect, useRef } from "react"

/*
 * Screen Wake Lock during multi-shot camera capture (Task 7 / B5a).
 *
 * `CameraCapture.tsx` calls `useWakeLock(phase === "live" && started)` — a
 * multi-page scan is the one flow in this product where the screen turning
 * off mid-shoot actually loses work (the stream stops, the student has to
 * re-open the camera and re-frame). Every failure here is swallowed: a wake
 * lock is a nicety, not a requirement the capture flow depends on.
 *
 * No unit test exists for this hook — it is DOM/effect-driven and this
 * repo's unit runner has no jsdom (`vitest.config.ts`, D3.20); it is
 * exercised only by `capabilityWiring.test.ts`'s source-text gate and by
 * manual verification. Modelled on `PushAutoEnable`'s "every failure is
 * silent" shape.
 */
export function useWakeLock(active: boolean): void {
  const lockRef = useRef<WakeLockSentinel | null>(null)

  useEffect(() => {
    if (!active) return
    if (typeof navigator === "undefined" || !navigator.wakeLock) return

    let cancelled = false

    const acquire = async () => {
      try {
        const lock = await navigator.wakeLock.request("screen")
        if (cancelled) {
          await lock.release()
          return
        }
        lockRef.current = lock
      } catch {
        // A wake lock is a nicety — every failure (denied, unsupported at
        // the moment of the call, tab backgrounded mid-request) is silent.
      }
    }

    void acquire()

    // A wake lock is released automatically when the document becomes
    // hidden (e.g. the OS camera permission prompt, or the reader switching
    // apps mid-capture) and does not reacquire itself when it becomes
    // visible again — this is what re-requests it.
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void acquire()
    }
    document.addEventListener("visibilitychange", onVisibilityChange)

    return () => {
      cancelled = true
      document.removeEventListener("visibilitychange", onVisibilityChange)
      lockRef.current?.release().catch(() => {
        // Already released, or the release itself failed — either way there
        // is nothing left to hold onto.
      })
      lockRef.current = null
    }
  }, [active])
}
