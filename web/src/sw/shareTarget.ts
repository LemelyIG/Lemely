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
 * Stashes `file` into Cache Storage under `SHARE_KEY`, with the three
 * headers `readSharedScan` (`src/lib/sharedScan.ts`) reads back out.
 *
 * Exported on its own — not just inlined into `handleShareTargetFetch` —
 * because it is also the File Handling API's stash path: `main.tsx`'s
 * file-handler bridge calls this directly for a file that arrived via
 * `window.launchQueue`, not a share-target POST, so both delivery
 * mechanisms funnel into the same one Cache Storage entry `CorrectPaper.tsx`
 * reads on mount.
 *
 * Can throw: `Headers` validates its values against the Fetch spec's
 * forbidden-byte set, and `file.name` is attacker- or OS-controlled input —
 * `handleShareTargetFetch` below is what catches this, not this function,
 * so a page-side caller (the file-handler bridge) sees a real rejection
 * rather than a silently-dropped file.
 */
export async function stashSharedFile(file: File): Promise<void> {
  const cache = await caches.open(SHARE_CACHE)
  const headers = new Headers({
    "content-type": file.type || "application/octet-stream",
    "x-shared-name": file.name,
    "x-shared-at": new Date().toISOString(),
  })
  await cache.put(SHARE_KEY, new Response(file, { headers }))
}

/**
 * Stashes the shared file into Cache Storage and redirects to the marking
 * flow. `CorrectPaper.tsx`'s `readSharedScan` (src/lib/sharedScan.ts) is the
 * other half — it reads this exact cache/key on mount.
 *
 * Always redirects, file or not: a share sheet is not somewhere to render an
 * error, and a share with no file (or a browser that omitted it) still needs
 * to leave the reader somewhere real rather than on a blank POST response.
 * The same holds for a file whose name `stashSharedFile` can't turn into a
 * header value (A6 review fix MEDIUM 2) — stashing is best-effort, but the
 * redirect is not optional.
 */
export async function handleShareTargetFetch(event: ShareTargetFetchEvent): Promise<Response> {
  // The try now opens before `formData()`, not just around `stashSharedFile`
  // — a malformed multipart body can reject there too, and this function's
  // own "always redirects" contract has to hold for that case as well.
  try {
    const formData = await event.request.formData()
    const file = formData.get("scan")

    if (file instanceof File) {
      await stashSharedFile(file)
    }
  } catch {
    // Deliberately empty. See this function's own doc comment.
  }

  // An absolute URL, built off the request's own origin, rather than the bare
  // path `Response.redirect("/scan-inbox", 303)` accepts in a browser:
  // Node's `Response.redirect` (used by `swShareTarget.test.ts`, which has no
  // page origin to resolve a relative path against) requires one, and
  // resolving explicitly works identically in a real service worker too.
  // `/scan-inbox` (not the student-only `/student/correct`) is the
  // role-aware landing `scanInboxDestination.ts` resolves per session —
  // this handler has no session/role visibility of its own to do that here.
  return Response.redirect(new URL("/scan-inbox", event.request.url), 303)
}
