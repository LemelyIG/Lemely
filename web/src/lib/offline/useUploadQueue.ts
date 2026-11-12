import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { runCorrection, uploadScan } from "@/lib/hooks/useStudentApi"
import { drainUploadQueue, listQueuedUploads, type QueuedUpload } from "@/lib/offline/uploadQueue"

/*
 * Task 10 (B6b) — the page half of draining the offline upload queue.
 *
 * Three triggers, all funnelling into the same `drain()`: mount (a queue
 * left over from before this tab existed, or a page reload while still
 * offline followed by a fresh mount once connectivity returns), the
 * browser's own `online` event, and a message from the service worker's own
 * Background Sync attempt (`sw.ts`'s `Queue("lemely-uploads", { onSync })`).
 * That last one matters even though the worker cannot authenticate its own
 * upload/correct calls (it has no access to the `localStorage`-held bearer
 * token — see `queueDecision.ts`'s comment on why this whole module tree
 * stays reachable from `sw.ts` at all) — a Background Sync event can still
 * fire while this tab is open but backgrounded/throttled on mobile, and the
 * worker's message is what wakes this hook to do the real, authenticated
 * work rather than waiting for the reader to refocus the tab.
 *
 * `drainUploadQueue` is intentionally re-run on every trigger rather than
 * gated on "do we know the queue is non-empty": it is idempotent (an empty
 * queue drains to nothing in one cheap `listQueuedUploads` call), and a
 * `count` this hook itself computed a render ago can already be stale by
 * the time an event fires.
 */

const SW_DRAIN_MESSAGE = "UPLOAD_QUEUE_DRAINED"

/** Turn one queued entry's `Blob`s back into the `File`s `uploadScan`
 * expects. `File`'s own `name`/`type` do not survive a trip through
 * IndexedDB (only the `QueuedUpload` record's own fields do), so they are
 * rebuilt from what was saved alongside the bytes. */
async function uploadQueuedEntry(entry: QueuedUpload): Promise<{ paperId: string }> {
  const scan = new File([entry.scan], entry.scanName, {
    type: entry.scan.type || "application/octet-stream",
  })
  const markScheme = entry.markScheme
    ? new File([entry.markScheme], "mark_scheme.pdf", {
        type: entry.markScheme.type || "application/pdf",
      })
    : undefined
  return uploadScan(scan, markScheme, { idempotencyKey: entry.idempotencyKey })
}

/**
 * Kick off marking for a paper the queue just uploaded, without driving any
 * stage UI for it — there is none to drive; this is a background drain, not
 * a screen the reader is watching. `POST /student/correct` marks on a
 * background thread that outlives the request (`useStudentApi.ts`'s own
 * comment on `useActiveUpload`/`useUploadRun`), so reading exactly one frame
 * is enough to guarantee the request reached the server and the run began —
 * recovery (the existing "a run that was already going when this screen
 * loaded" panel in `CorrectPaper.tsx`) takes it from there. Breaking out of
 * `for await` calls the async generator's own `return()`, which is what
 * releases the underlying stream reader.
 */
async function correctQueuedPaper(paperId: string): Promise<void> {
  for await (const _frame of runCorrection(paperId)) {
    break
  }
}

export interface UseUploadQueueResult {
  /** How many uploads are currently queued. */
  count: number
  /** Manually nudge a drain, for a reader who does not want to wait for the
   * next automatic trigger. */
  retry: () => void
}

export function useUploadQueue(): UseUploadQueueResult {
  const [count, setCount] = useState(0)
  const draining = useRef(false)
  const queryClient = useQueryClient()

  const refreshCount = useCallback(async () => {
    const entries = await listQueuedUploads()
    setCount(entries.length)
  }, [])

  const drain = useCallback(() => {
    // Re-entrant triggers (mount + an `online` event firing in the same
    // tick, say) must not run two drains over the same entries at once —
    // `drainUploadQueue` has no locking of its own, and a concurrent second
    // pass could double-upload an entry the first pass has already started.
    if (draining.current) return
    draining.current = true
    drainUploadQueue({ upload: uploadQueuedEntry, correct: correctQueuedPaper })
      .catch(() => {
        // A failed attempt leaves its entries queued (`drainUploadQueue`
        // bumps `attempts` itself); nothing here needs its own error
        // surface — `refreshCount` below still reflects the real count.
      })
      .finally(() => {
        draining.current = false
        void refreshCount()
        // A drained entry may have just started a marking run this tab was
        // not already watching — the same "recovered run" path a reload
        // triggers (`useActiveUpload`/`useUploadRun` in `useStudentApi.ts`).
        void queryClient.invalidateQueries({ queryKey: ["student", "upload", "active"] })
      })
  }, [queryClient, refreshCount])

  useEffect(() => {
    void refreshCount()
    drain()

    window.addEventListener("online", drain)
    const onMessage = (event: MessageEvent): void => {
      const data = event.data as { type?: unknown } | undefined
      if (data?.type === SW_DRAIN_MESSAGE) drain()
    }
    navigator.serviceWorker?.addEventListener("message", onMessage)

    return () => {
      window.removeEventListener("online", drain)
      navigator.serviceWorker?.removeEventListener("message", onMessage)
    }
  }, [drain, refreshCount])

  return { count, retry: drain }
}
