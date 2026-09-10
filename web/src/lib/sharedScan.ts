import { SHARE_CACHE, SHARE_KEY } from "@/sw/shareTarget"

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
