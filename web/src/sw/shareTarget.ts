/*
 * Handles the Web Share Target POST that `vite/manifest.ts`'s `share_target`
 * registers, and the two constants both halves of that flow — this
 * worker-context handler and the page-context `readSharedScan` in
 * `src/lib/sharedScan.ts` — need to agree on.
 *
 * Deliberately typed without any WebWorker-exclusive global: no real
 * `FetchEvent`, no `self`. `caches`/`Response`/`Headers`/`Request`/`File` are
 * declared in both `lib.dom.d.ts` and `lib.webworker.d.ts`, so this file
 * compiles cleanly whether it lands in the app's DOM project or the service
 * worker's WebWorker project — the same "pure enough to live in both" shape
 * `lib/push/pushDecision.ts` already established for the push half of
 * `sw.ts`. `ShareTargetFetchEvent` below is the narrow event shape this
 * needs (just `.request`), not the real global `FetchEvent`, precisely so a
 * test running under `vitest.config.ts`'s Node environment (no WebWorker
 * lib) can construct a fake one without pulling in worker-only types it
 * doesn't otherwise need.
 */

export const SHARE_CACHE = "lemely-share-target"
export const SHARE_KEY = "/__shared-scan"

export interface ShareTargetFetchEvent {
  request: Request
}

/**
 * Stashes the shared file into Cache Storage and redirects to the marking
 * flow. `CorrectPaper.tsx`'s `readSharedScan` (src/lib/sharedScan.ts) is the
 * other half — it reads this exact cache/key on mount.
 *
 * Always redirects, file or not: a share sheet is not somewhere to render an
 * error, and a share with no file (or a browser that omitted it) still needs
 * to leave the reader somewhere real rather than on a blank POST response.
 */
export async function handleShareTargetFetch(event: ShareTargetFetchEvent): Promise<Response> {
  const formData = await event.request.formData()
  const file = formData.get("scan")

  if (file instanceof File) {
    const cache = await caches.open(SHARE_CACHE)
    const headers = new Headers({
      "content-type": file.type || "application/octet-stream",
      "x-shared-name": file.name,
      "x-shared-at": new Date().toISOString(),
    })
    await cache.put(SHARE_KEY, new Response(file, { headers }))
  }

  // An absolute URL, built off the request's own origin, rather than the bare
  // path `Response.redirect("/student/correct", 303)` accepts in a browser:
  // Node's `Response.redirect` (used by `swShareTarget.test.ts`, which has no
  // page origin to resolve a relative path against) requires one, and
  // resolving explicitly works identically in a real service worker too.
  return Response.redirect(new URL("/student/correct", event.request.url), 303)
}
