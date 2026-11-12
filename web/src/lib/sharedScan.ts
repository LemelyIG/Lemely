import { SHARE_CACHE, SHARE_KEY, stashSharedFile } from "@/sw/shareTarget"

/**
 * How long a shared file waits in Cache Storage for `CorrectPaper.tsx` to
 * pick it up. A share sheet is a synchronous-feeling action, so ten minutes
 * comfortably covers app-switch latency and a slow install/launch, while
 * still not leaving a photo of a past paper sitting in Cache Storage
 * indefinitely if the reader never got back to the app.
 */
const SHARED_SCAN_TTL_MS = 10 * 60 * 1000

/**
 * Reads the file `handleShareTargetFetch` (src/sw/shareTarget.ts) stashed
 * from a Web Share Target POST, if any is still fresh.
 *
 * The entry is deleted either way — fresh or stale — once read: a share
 * consumed into the marking flow should not be offered again on the next
 * visit to this screen, and a stale one is not worth keeping past its TTL.
 */
export async function readSharedScan(): Promise<File | null> {
  // A file-handler launch may still be mid-stash (`installFileHandlerBridge`
  // below) — see `pendingStash`'s own doc for why this has to wait rather
  // than racing it.
  if (pendingStash) await pendingStash

  const cache = await caches.open(SHARE_CACHE)
  const response = await cache.match(SHARE_KEY)
  if (!response) return null

  await cache.delete(SHARE_KEY)

  const sharedAt = response.headers.get("x-shared-at")
  const age = sharedAt ? Date.now() - new Date(sharedAt).getTime() : Number.POSITIVE_INFINITY
  if (!Number.isFinite(age) || age > SHARED_SCAN_TTL_MS) return null

  const blob = await response.blob()
  const name = response.headers.get("x-shared-name") ?? "shared-scan"
  const type = response.headers.get("content-type") ?? blob.type
  return new File([blob], name, { type })
}

/**
 * The file-handler bridge's in-flight stash, if one is currently running.
 *
 * `readSharedScan()` awaits this before touching the cache — without it, a
 * reader that mounts while a stash is still in progress (a multi-MB photo's
 * `getFile()` -> `caches.open` -> `cache.put` chain has several async hops)
 * races it instead of waiting for it, and a reader whose `cache.match` runs
 * first finds nothing: the launched file is silently dropped with no retry,
 * since the File Handling API delivers a launch exactly once. Reset to
 * `null` once the stash settles (success or failure) so a later, unrelated
 * call to `readSharedScan` never lines up behind a stale promise nobody
 * started a wait for.
 */
let pendingStash: Promise<void> | null = null

/**
 * File Handling API (manifest's `file_handlers`) — the OS "open with
 * Lemely" counterpart to the Web Share Target. Registered once, at the app
 * root (`main.tsx`), the same "call once, before the app renders" shape
 * `installStaleChunkReload`/`registerPushClientBridge` already use there —
 * not inside `CorrectPaper.tsx` (A6 review fix MEDIUM 4): that screen can
 * unmount (the reader navigates away) while still registered as
 * `launchQueue`'s only consumer, since the File Handling API has no
 * matching "unset consumer" call — a REPEAT OS launch arriving after that
 * would reach a consumer closed over an unmounted component's now-inert
 * state setters and silently no-op.
 *
 * Stashes into the exact same Cache Storage entry the share-target flow
 * uses (`stashSharedFile`, `src/sw/shareTarget.ts`), so `readSharedScan` on
 * `CorrectPaper.tsx`'s mount picks it up regardless of which OS mechanism
 * actually delivered the file — one bridge, two OS entry points.
 *
 * `window.launchQueue` is undefined outside Chromium, so this is a no-op
 * everywhere else.
 */
export function installFileHandlerBridge(): void {
  window.launchQueue?.setConsumer((launchParams) => {
    const handle = launchParams.files[0]
    // `files` is `FileSystemHandle[]` (vite-env.d.ts's own doc explains
    // why) — only the "file" kind has `.getFile()`; the manifest's
    // `file_handlers` never declares a directory accept type, but the
    // narrowing still has to happen somewhere, and it belongs here.
    // `FileSystemHandle` is a plain base interface, not a discriminated
    // union of `FileSystemFileHandle | FileSystemDirectoryHandle`, so
    // checking `.kind` alone doesn't let TS narrow the type on its own —
    // the cast is what the DOM lib's own shape requires here, once the
    // runtime check above has actually confirmed it.
    if (!handle || handle.kind !== "file") return
    const fileHandle = handle as FileSystemFileHandle
    const stash = fileHandle
      .getFile()
      .then((file) => stashSharedFile(file))
      .catch(() => {
        // Best-effort, matching handleShareTargetFetch's own contract for
        // the share-target half of this bridge — a malformed name (or a
        // `getFile()` failure) must not crash the launch consumer, and must
        // not reject `pendingStash` out from under a concurrent
        // `readSharedScan()` awaiting it either.
      })
    pendingStash = stash
    void stash.finally(() => {
      // Only clear if nothing newer has already taken over — a second
      // launch arriving before this one's cleanup runs must not have its
      // own in-flight `pendingStash` erased by the first one settling late.
      if (pendingStash === stash) pendingStash = null
    })
  })
}
