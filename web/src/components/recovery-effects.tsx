/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { currentBuildId } from "@/lib/clientErrors"
import { useOnlineStatus } from "@/lib/online"
import { StaleChunkGuard } from "@/lib/staleChunk"
import { useToast, type ToastOptions } from "@/components/ui/toast"

/*
 * PR 2 part C · the two "recovery is automatic and announced" effects
 * (product's approved design for this PR). App-level, not a kit primitive —
 * this renders nothing and exists purely to sit inside the provider tree
 * (`main.tsx`, alongside `ToastProvider`) and run two effects for the whole
 * app's lifetime. Stamped anyway: `hallmarkStamp.test.ts`'s gate covers all
 * of `src/components/**`, not just `components/ui/`, so this file needs one
 * regardless of not being a kit primitive.
 *
 * (a) Reconnect: the moment the browser goes offline→online, every *active*
 * query currently sitting in an error state refetches itself, followed by a
 * "Reconnected" toast — a reader never has to notice a page is stale and
 * manually refresh it. `type: "active"` deliberately excludes background
 * (unmounted, cached) queries: refetching those on every reconnect would
 * spend Gemini-backed and ordinary API budget on screens nobody is looking
 * at, for a promise ("this page will refresh by itself") this design only
 * makes about pages that are open.
 *
 * (b) Update notice: on mount, ask the stale-chunk guard (`lib/staleChunk.ts`)
 * whether this load is the other side of a reload it caused. If so, an
 * "Updated to the latest version" toast tells the reader why the page just
 * reloaded out from under them, instead of leaving that silent.
 */

/**
 * Pure decision: did this online-status transition cross from offline to
 * online? Exported so `recoveryEffects.test.ts` can pin it without mounting
 * a component — this repo's unit suite runs under Node with no jsdom
 * (`vitest.config.ts`, D3.20).
 */
export function shouldAnnounceReconnect(prev: boolean, next: boolean): boolean {
  return !prev && next
}

/*
 * Constructed lazily, on first real use, rather than at module scope: a
 * module-scope `new StaleChunkGuard(window.localStorage)` would run the
 * moment anything imports this file, including `recoveryEffects.test.ts`
 * importing `shouldAnnounceReconnect` under vitest's `node` environment,
 * where `window` does not exist. `main.tsx`'s own `installStaleChunkReload`
 * call constructs a separate `StaleChunkGuard` instance, which is fine: both
 * wrap the same real `window.localStorage`, so they agree on state without
 * needing to be the same object.
 */
let guard: StaleChunkGuard | null = null
function getGuard(): StaleChunkGuard {
  guard ??= new StaleChunkGuard(window.localStorage)
  return guard
}

/**
 * The two announcements, as data, so the dev-preview kit can render the same
 * copy `RecoveryEffects` fires without faking a reconnect or a reload.
 */
export const RECONNECTED_TOAST: ToastOptions = {
  title: "Reconnected",
  description: "Anything that failed to load has been fetched again.",
  variant: "success",
}

export const UPDATED_TOAST: ToastOptions = {
  title: "Updated to the latest version",
  description: "Lemely reloaded to pick up a new release. Nothing you did was lost.",
  variant: "info",
}

export function RecoveryEffects() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const online = useOnlineStatus()
  const wasOnline = useRef(online)

  useEffect(() => {
    if (shouldAnnounceReconnect(wasOnline.current, online)) {
      void queryClient.refetchQueries({
        type: "active",
        predicate: (query) => query.state.status === "error",
      })
      toast(RECONNECTED_TOAST)
    }
    wasOnline.current = online
  }, [online, queryClient, toast])

  useEffect(() => {
    if (getGuard().consumeReloadNotice(currentBuildId())) {
      toast(UPDATED_TOAST)
    }
    // Runs once on mount only — a reload notice, by definition, is only ever
    // pending on the render right after the reload that set it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return null
}
