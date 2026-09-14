import type { QueuedUpload } from "@/lib/offline/uploadQueue"

/*
 * Task 10 (B6b) — pure decision logic for the offline upload queue. Kept
 * apart from `uploadQueue.ts`'s IDB plumbing so both can be driven by
 * vitest with no store, no DOM, and no network at all.
 *
 * Deliberately does NOT `import { ApiError } from "@/lib/api"`, even though
 * `shouldQueueUpload` below exists to recognise one: `sw.ts`'s `Queue`
 * imports `drainUploadQueue` from `uploadQueue.ts`, which imports
 * `nextQueueAction` from this file, and `tsconfig.sw.json`'s own header
 * comment names the exact failure a `lib/api` import causes there —
 * `api.ts` reaches `auth/storage.ts`, which reads `localStorage`, which does
 * not exist under the worker's `WebWorker` lib. TypeScript checks a whole
 * imported file, not just the export a caller happens to use, so keeping
 * `ApiError` out of this module's own imports is what keeps that page-only
 * dependency from leaking into the worker's compile graph. `shouldQueueUpload`
 * duck-types the one field it needs instead.
 */

/**
 * Whether a failed upload attempt should be queued for a later retry.
 *
 * `lib/api.ts` already normalises every transport failure — a dropped
 * connection included — into `ApiError(0, ...)` before it ever reaches a
 * caller (see that module's own header comment, and `isOfflineFailure` in
 * `lib/offlineFailure.ts`, which this mirrors: status `0` and nothing else).
 * A real 4xx/5xx from the server is a decision the server made and must
 * never be retried silently — a 422 malformed request or a 409 conflict
 * queued for later would just fail identically on replay, having told the
 * reader nothing.
 */
export function shouldQueueUpload(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status: unknown }).status === 0
  )
}

/** After 24h or 5 attempts, an entry is abandoned rather than retried
 * forever — a scan from three days ago is not one the student still wants
 * silently uploaded and marked without them there to see it. */
const MAX_QUEUE_AGE_MS = 24 * 60 * 60 * 1000
const MAX_ATTEMPTS = 5

export type QueueAction = "upload" | "correct" | "drop"

/**
 * What should happen next to a queued entry.
 *
 * Age and attempt-count are checked before status: an entry that has already
 * uploaded but is too old or has failed `correct` too many times must still
 * be dropped, not corrected forever.
 */
export function nextQueueAction(entry: QueuedUpload, now: number): QueueAction {
  if (now - entry.createdAt > MAX_QUEUE_AGE_MS) return "drop"
  if (entry.attempts >= MAX_ATTEMPTS) return "drop"
  if (entry.status === "uploaded" && entry.paperId) return "correct"
  return "upload"
}
