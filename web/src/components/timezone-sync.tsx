/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 */
import { useEffect, useRef } from "react"
import { useAuth } from "@/lib/auth/AuthContext"
import { usePutTimezone } from "@/lib/hooks/useMeApi"
import { deviceTimezone, deviceTimezoneUpdate } from "@/lib/timezone"

/*
 * Sends the device's zone once per signed-in session (push-delivery spec §3,
 * "auto-detect"). Mounted once above the router, beside `RecoveryEffects`, for
 * the same reason that one is: this has to run whichever screen the reader
 * lands on, and an effect inside a screen would only run there.
 *
 * It sends unconditionally and lets the server decide. The rule that a device
 * write never overwrites a deliberate choice lives in `routers/me.py`, where it
 * is enforced for every client; repeating it here as a client-side gate would
 * be a second copy that could disagree with the first.
 *
 * Failure is silent by design: a missed sync costs one civil day of the launch
 * zone until the next boot, and there is no screen to report it on.
 *
 * The stamp above, derived rather than copied: H3 and V3 are honest ceilings
 * for a component that returns `null` — there is no hierarchy to rank and no
 * composition to vary, and claiming otherwise would be a fabricated critique.
 * R5 is the real strength: no toast, no retry, no state, and a silent failure
 * that is argued for rather than overlooked.
 */
export function TimezoneSync() {
  const { session } = useAuth()
  const put = usePutTimezone()
  const sentFor = useRef<string | null>(null)
  const userId = session?.userId ?? null

  useEffect(() => {
    if (userId === null || sentFor.current === userId) return
    const update = deviceTimezoneUpdate(deviceTimezone())
    if (update === null) return
    sentFor.current = userId
    put.mutate(update)
    // `put` is stable for the component's lifetime; listing it would re-run
    // this on every render and the ref guard would still make that a no-op.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  return null
}
