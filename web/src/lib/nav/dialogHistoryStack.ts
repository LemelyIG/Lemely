import { nextDialogHistoryAction } from "@/lib/nav/dialogHistory"

/*
 * Which overlay a back press belongs to.
 *
 * `popstate` is a window event, so every mounted `useDialogHistory` hears
 * every back press. With each instance deciding for itself, a `ConfirmModal`
 * opened over a `Modal` had two listeners answering one press: both closed,
 * and one of the two pushed entries stayed in the history. Overlays stack
 * visually, so they must stack in history too — one press unwinds exactly the
 * topmost.
 *
 * `expectSelfPop` is the other half. The guard against "is this popstate our
 * own `navigate(-1)` coming back to us?" cannot live in a per-instance ref
 * either: an overlay that unwinds itself removes its entry from this stack
 * *synchronously*, while the popstate its `navigate(-1)` causes arrives a tick
 * later — by which point the instance below would wrongly take it for a real
 * back press and close too.
 */

export interface DialogHistoryEntry {
  /** Read live: a `Modal` can flip `dismissible` while open. */
  isDismissible: () => boolean
  close: () => void
  repush: () => void
  /** Read live: is the current history entry the one this overlay pushed? */
  isCurrent: () => boolean
}

/** A history move of ours whose popstate has not arrived after this long never will (`navigate(-1)` at the first entry fires none). */
export const SELF_POP_EXPIRY_MS = 1000

export type PopStateOutcome = "self" | "none" | "closeOnly" | "repush"

export function createDialogHistoryStack() {
  const entries: DialogHistoryEntry[] = []
  let pendingSelfPops = 0
  // Work that needs the history cursor settled: it runs on the popstate of the move in flight.
  const afterSelfPop: Array<() => void> = []
  // One expiry per move in flight, oldest first, so a move that never reports cannot leave the count stuck.
  const expiries: Array<ReturnType<typeof setTimeout>> = []

  return {
    /** Call when an overlay has pushed its history entry. Returns the release. */
    register(entry: DialogHistoryEntry): () => void {
      entries.push(entry)
      return () => {
        const at = entries.lastIndexOf(entry)
        if (at !== -1) entries.splice(at, 1)
      }
    },

    /** Is a history move of our own still in flight (its popstate has not arrived)? */
    hasPendingSelfPop(): boolean {
      return pendingSelfPops > 0
    },

    /** A move in flight or an unwind waiting on one: the window listener must stay up for either. */
    hasPendingWork(): boolean {
      return pendingSelfPops > 0 || afterSelfPop.length > 0
    },

    /**
     * Run `fn` once the move in flight has landed, and the cursor reads true. Stacked overlays that
     * close in one tick need this: the second `navigate(-1)` would otherwise look at the history entry
     * before the first has popped, see the wrong entry, and skip, leaving its own entry orphaned.
     */
    afterNextSelfPop(fn: () => void): void {
      afterSelfPop.push(fn)
    },

    /** Call immediately before moving the history cursor ourselves. */
    expectSelfPop(): void {
      pendingSelfPops += 1
      const expiry: ReturnType<typeof setTimeout> = setTimeout(() => {
        const at = expiries.indexOf(expiry)
        if (at === -1) return
        expiries.splice(at, 1)
        pendingSelfPops = Math.max(0, pendingSelfPops - 1)
        afterSelfPop.shift()?.()
      }, SELF_POP_EXPIRY_MS)
      expiries.push(expiry)
    },

    handlePopState(): PopStateOutcome {
      if (pendingSelfPops > 0) {
        pendingSelfPops -= 1
        const expiry = expiries.shift()
        if (expiry !== undefined) clearTimeout(expiry)
        // One deferred unwind per popstate: each runs against the cursor the move before it left,
        // and queues its own `expectSelfPop`, so a third waits for the second's popstate in turn.
        afterSelfPop.shift()?.()
        return "self"
      }

      const top = entries[entries.length - 1]
      if (!top) return "none"

      const action = nextDialogHistoryAction({
        event: "popstate",
        dismissible: top.isDismissible(),
        hasEntry: true,
      })

      if (action === "closeOnly") {
        top.close()
        return "closeOnly"
      }
      if (action === "repush") {
        top.repush()
        return "repush"
      }
      return "none"
    },

    /**
     * True when the current history entry is the top-most open overlay's own
     * pushed entry. A navigation out of the overlay should then REPLACE that
     * entry, so one Back from the destination returns to the origin.
     */
    topEntryIsCurrent(): boolean {
      const top = entries[entries.length - 1]
      return top ? top.isCurrent() : false
    },

    get size(): number {
      return entries.length
    },
  }
}

export const dialogHistoryStack = createDialogHistoryStack()
