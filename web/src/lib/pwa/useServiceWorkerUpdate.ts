import { useEffect, useState } from "react"
import { useRegisterSW } from "virtual:pwa-register/react"
import { scheduleUpdateChecks } from "./updateScheduler"

/*
 * Packet A7 — gated service-worker updates (the `silent-update-swap` ledger
 * finding).
 *
 * Before this packet, `sw.ts` called `self.skipWaiting()` unconditionally on
 * install and `vite.config.ts` set `registerType: "autoUpdate"`, which
 * together made vite-plugin-pwa's own `registerSW.ts` skip its `waiting`
 * stage entirely and reload every open tab the moment a new worker
 * activated — no consent, possibly mid-interaction. `registerType: "prompt"`
 * (now set in `vite.config.ts`) is what makes `onNeedRefresh` fire at all
 * instead of that silent path; `sw.ts`'s `self.skipWaiting()` now runs only
 * from a `message` listener, so the new worker stays in `waiting` until
 * `applyUpdate` below tells it to take over.
 *
 * `updateServiceWorker(true)` already does the rest: vite-plugin-pwa's own
 * `registerSW.ts` sends the `SKIP_WAITING` message via workbox-window's
 * `messageSkipWaiting()`, then reloads once the new worker's `controlling`
 * event fires. There is nothing left for this hook to do by hand.
 *
 * The update-check polling itself (`scheduleUpdateChecks`) lives in
 * `updateScheduler.ts`, a sibling module with no `virtual:pwa-register/react`
 * import of its own — see that file's header for why the split is load-
 * bearing, not just tidiness.
 */

export interface ServiceWorkerUpdateState {
  needRefresh: boolean
  applyUpdate: () => void
}

export function useServiceWorkerUpdate(): ServiceWorkerUpdateState {
  const [registration, setRegistration] = useState<ServiceWorkerRegistration | null>(null)

  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, reg) {
      setRegistration(reg ?? null)
    },
  })

  useEffect(() => {
    if (!registration) return
    return scheduleUpdateChecks(registration)
  }, [registration])

  return {
    needRefresh,
    applyUpdate: () => {
      void updateServiceWorker(true)
    },
  }
}
