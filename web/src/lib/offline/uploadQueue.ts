import { del, get, keys, set } from "idb-keyval"
import { nextQueueAction } from "@/lib/offline/queueDecision"

/*
 * Task 10 (B6b) — the offline upload queue's own storage and drain logic.
 *
 * DOM-free by construction: `idb-keyval` reaches only `indexedDB`, which
 * exists in both a page and a service worker, so this whole module is
 * importable from `sw.ts` (see that file's `Queue("lemely-uploads", {
 * onSync: ... })`) as well as from the page's own `useUploadQueue.ts` hook.
 * Neither the store nor `drainUploadQueue` below knows anything about
 * authentication, `fetch`, or React — the actual `upload`/`correct` network
 * calls are injected by the caller, which is what lets the exact same drain
 * logic run with a live page session (real bearer token, real
 * `uploadScan`/`runCorrection`) and inside a worker that has no access to
 * `localStorage` at all (see `queueDecision.ts`'s own comment on why this
 * file must not import anything that reaches `lib/api.ts`).
 */

/** One paper waiting to be uploaded (or already uploaded, waiting for
 * `/student/correct`). Mirrors exactly what a student picked — the scan and
 * mark-scheme `File`s, read down to `Blob` so they survive a trip through
 * IndexedDB — plus the `Idempotency-Key` this entry sends on every attempt,
 * page or worker, so a request that in fact already reached the server
 * (Task 9's dedupe window) is never double-charged against Gemini or double
 * stored. Deliberately carries no credential of any kind — see
 * `AuthContext.tsx`'s `clearUploadQueue()` call and this file's own
 * `clearUploadQueue` below: the only secret this store ever holds is the
 * scan itself, which sign-out clears same as everything else session-scoped. */
export interface QueuedUpload {
  id: string
  idempotencyKey: string
  scan: Blob
  scanName: string
  markScheme: Blob | null
  createdAt: number
  attempts: number
  status: "queued" | "uploaded"
  paperId?: string
}

/** The `idb-keyval`-shaped surface this module actually uses — narrow enough
 * that a test can hand it an in-memory `Map`-backed fake instead of touching
 * real `indexedDB`. */
export interface UploadQueueAdapter {
  get<T>(key: string): Promise<T | undefined>
  set<T>(key: string, value: T): Promise<void>
  del(key: string): Promise<void>
  keys(): Promise<string[]>
}

const defaultStore: UploadQueueAdapter = {
  get: (key) => get(key),
  set: (key, value) => set(key, value),
  del: (key) => del(key),
  keys: async () => (await keys()).map(String),
}

/** Every entry lives under its own `idb-keyval` key, prefixed so
 * `listQueuedUploads`/`clearUploadQueue` can enumerate just this store's own
 * rows out of a shared IndexedDB database without touching anything else a
 * caller might keep there (`queryPersister.ts`'s persisted query cache
 * included). */
const QUEUE_PREFIX = "lemely-upload:"
const keyFor = (id: string): string => `${QUEUE_PREFIX}${id}`

/** Add a new upload to the queue, queued and unattempted. */
export async function enqueueUpload(
  entry: Omit<QueuedUpload, "attempts" | "status">,
  store: UploadQueueAdapter = defaultStore,
): Promise<void> {
  const full: QueuedUpload = { ...entry, attempts: 0, status: "queued" }
  await store.set(keyFor(entry.id), full)
}

/** Every entry currently queued, in no particular order. */
export async function listQueuedUploads(
  store: UploadQueueAdapter = defaultStore,
): Promise<QueuedUpload[]> {
  const allKeys = await store.keys()
  const entries = await Promise.all(
    allKeys
      .filter((key) => key.startsWith(QUEUE_PREFIX))
      .map((key) => store.get<QueuedUpload>(key)),
  )
  return entries.filter((entry): entry is QueuedUpload => entry !== undefined)
}

/** Record that an entry's scan reached the server, so a later drain that is
 * interrupted between the upload and the correction call resumes at
 * `correct` rather than re-uploading a scan the server already has. */
export async function markUploaded(
  id: string,
  paperId: string,
  store: UploadQueueAdapter = defaultStore,
): Promise<void> {
  const existing = await store.get<QueuedUpload>(keyFor(id))
  if (!existing) return
  await store.set(keyFor(id), { ...existing, status: "uploaded", paperId })
}

/** Drop one entry — a successful drain, or one `nextQueueAction` has given
 * up on. */
export async function removeQueued(
  id: string,
  store: UploadQueueAdapter = defaultStore,
): Promise<void> {
  await store.del(keyFor(id))
}

/** Drop every queued entry. `AuthContext.tsx`'s `logout()` calls this — the
 * scans in here are session-scoped the same way every other cached read is,
 * and unlike a query-cache row, an entry here still holds the original
 * bytes, not just a JSON response. */
export async function clearUploadQueue(store: UploadQueueAdapter = defaultStore): Promise<void> {
  const allKeys = await store.keys()
  await Promise.all(
    allKeys.filter((key) => key.startsWith(QUEUE_PREFIX)).map((key) => store.del(key)),
  )
}

/** The network calls `drainUploadQueue` needs, injected so the exact same
 * drain logic runs with a real, authenticated page session or inside a
 * worker that has none. */
export interface DrainUploadQueueDeps {
  upload: (entry: QueuedUpload) => Promise<{ paperId: string }>
  correct: (paperId: string) => Promise<void>
  store?: UploadQueueAdapter
}

/**
 * Advance every queued entry by one step: upload it, or — if it already
 * uploaded on a previous, interrupted drain — just kick off
 * `/student/correct` for it. `nextQueueAction` decides which, and also
 * drops anything too old or too often retried before either network call is
 * attempted at all.
 *
 * An entry that fails stays queued with `attempts` bumped, for the next
 * drain (this same call, run again later, on a page or in the worker) to
 * retry — never removed on failure, only on success or on
 * `nextQueueAction`'s own give-up.
 */
export async function drainUploadQueue(
  deps: DrainUploadQueueDeps,
): Promise<{ drained: string[]; failed: string[] }> {
  const store = deps.store ?? defaultStore
  const now = Date.now()
  const entries = await listQueuedUploads(store)
  const drained: string[] = []
  const failed: string[] = []

  for (const entry of entries) {
    const action = nextQueueAction(entry, now)
    if (action === "drop") {
      await removeQueued(entry.id, store)
      continue
    }
    try {
      let paperId = entry.paperId
      if (action === "upload") {
        const uploaded = await deps.upload(entry)
        paperId = uploaded.paperId
        await markUploaded(entry.id, paperId, store)
      }
      // `paperId` is always set by this point: `action === "correct"` only
      // ever comes from `nextQueueAction` when `entry.paperId` is already
      // present, and the `upload` branch above just set it.
      await deps.correct(paperId as string)
      await removeQueued(entry.id, store)
      drained.push(entry.id)
    } catch {
      const current = await store.get<QueuedUpload>(keyFor(entry.id))
      if (current) await store.set(keyFor(entry.id), { ...current, attempts: current.attempts + 1 })
      failed.push(entry.id)
    }
  }

  return { drained, failed }
}
