/* Hallmark · pre-emit critique: P5 H4 E5 S4 R5 V4 */
import { useEffect, useRef } from "react"
import { useServiceWorkerUpdate } from "@/lib/pwa/useServiceWorkerUpdate"
import { useToast } from "@/components/ui/toast"
import { getUnsubmittedScanSnapshot } from "@/lib/activeScanGuard"

/*
 * Packet A7 — the page-side half of the gated service-worker update (see
 * `useServiceWorkerUpdate.ts`'s own header for the full mechanism).
 *
 * Renders nothing itself; fires a toast exactly once per `needRefresh`
 * transition to `true`, the same "effect that fires a side effect, not a
 * screen" shape `RecoveryEffects`/`TimezoneSync`/`PushAutoEnable` already
 * use in `main.tsx`. `duration: 0`: an update ready to apply should not
 * silently vanish after 5s the way a routine confirmation does — the reader
 * decides when to reload, not a timer.
 */
export function UpdateToast() {
  const { needRefresh, applyUpdate } = useServiceWorkerUpdate()
  const { toast } = useToast()
  const shown = useRef(false)

  useEffect(() => {
    if (!needRefresh || shown.current) return
    shown.current = true
    toast({
      title: "Update ready",
      description: "A new version of Lemely is ready to use.",
      duration: 0,
      action: { label: "Reload", onClick: handleReload },
    })
    // `toast` is stable for the app's lifetime (ToastProvider memoises it);
    // `handleReload` is a fresh closure every render but always does the
    // same thing, and the ref guard already makes this run at most once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needRefresh])

  /*
   * Checked at click time, not baked into the toast's creation-time
   * closure — `readSharedScan()` deletes its cache entry once read, so a
   * shared/launched scan lives only in `CorrectPaper.tsx`'s (or
   * `Grading.tsx`'s) React state; reloading out from under an unsubmitted
   * one loses it with no recovery path. See `activeScanGuard.ts`'s own doc.
   */
  const handleReload = () => {
    if (getUnsubmittedScanSnapshot()) {
      toast({
        title: "Finish your scan first",
        description: "Submit or discard the scan you're working on, then reload to update.",
        duration: 4000,
      })
      return
    }
    applyUpdate()
  }

  return null
}
