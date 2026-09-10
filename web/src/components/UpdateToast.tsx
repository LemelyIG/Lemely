import { useEffect, useRef } from "react"
import { useServiceWorkerUpdate } from "@/lib/pwa/useServiceWorkerUpdate"
import { useToast } from "@/components/ui/toast"

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
      action: { label: "Reload", onClick: applyUpdate },
    })
    // `toast` is stable for the app's lifetime (ToastProvider memoises it);
    // `applyUpdate` is a fresh closure every render but always does the same
    // thing, and the ref guard already makes this run at most once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needRefresh])

  return null
}
