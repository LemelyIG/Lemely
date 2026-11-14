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
 *
 * A move of ours is recognised by where it lands, not by a count and a clock.
 * `expectSelfPop(targetIdx)` records the history index the move ends on, and a
 * popstate is ours only when `history.state.idx` equals one of those targets.
 * A popstate that arrives late (a busy main thread, a slow traversal) still
 * lands on its target and is still ours; a real Back issued before it never lands on a
 * target while the move is outstanding, because traversals run in order. (A deferred unwind issues its move inside a
 * popstate handler, so a Back the user queued earlier can land on that target; the outcome is still what they asked for.)
 */

export interface DialogHistoryEntry {
  /** Read live: a `Modal` can flip `dismissible` while open. */
  isDismissible: () => boolean
  close: () => void
  repush: () => void
  /** Read live: is the current history entry the one this overlay pushed? */
  isCurrent: () => boolean
}

/**
 * Give-up time for a move of ours that never reports (a `navigate(-1)` with nowhere to go fires no popstate).
 * It is not how a late popstate is told apart from a real Back: that is the target index. A move landing
 * after this long is simply no longer expected, so keep it far above any real delay.
 */
export const SELF_POP_GIVE_UP_MS = 10_000

export type PopStateOutcome = "self" | "none" | "closeOnly" | "repush"

interface PendingMove {
  /** The history index the move ends on. */
  target: number
  /** Called once when the move lands, or when it is given up on. */
  onSettle: (() => void) | undefined
  giveUp: ReturnType<typeof setTimeout>
}

export function createDialogHistoryStack() {
  const entries: DialogHistoryEntry[] = []
  const moves: PendingMove[] = []
  // Work that needs the history cursor settled: it runs on the popstate of the move in flight.
  const afterSelfPop: Array<() => void> = []

  function settle(move: PendingMove) {
    clearTimeout(move.giveUp)
    move.onSettle?.()
  }

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
      return moves.length > 0
    },

    /** A move in flight or an unwind waiting on one: the window listener must stay up for either. */
    hasPendingWork(): boolean {
      return moves.length > 0 || afterSelfPop.length > 0
    },

    /**
     * Run `fn` once the move in flight has landed, and the cursor reads true. Stacked overlays that
     * close in one tick need this: the second `navigate(-1)` would otherwise look at the history entry
     * before the first has popped, see the wrong entry, and skip, leaving its own entry orphaned.
     * It also runs when a real Back lands with no move outstanding (the overlay above was closed by
     * Back, so the cursor is settled and what was waiting for it can go).
     */
    afterNextSelfPop(fn: () => void): void {
      afterSelfPop.push(fn)
    },

    /**
     * Call immediately before moving the history cursor ourselves, with the index the move ends on.
     * `onSettle` runs when that move lands or is given up on.
     */
    expectSelfPop(targetIdx: number, onSettle?: () => void): void {
      const move: PendingMove = {
        target: targetIdx,
        onSettle,
        giveUp: setTimeout(() => {
          const at = moves.indexOf(move)
          if (at === -1) return
          moves.splice(at, 1)
          settle(move)
          afterSelfPop.shift()?.()
        }, SELF_POP_GIVE_UP_MS),
      }
      moves.push(move)
    },

    /** `currentIdx` is the history index the popstate landed on (`history.state.idx`). */
    handlePopState(currentIdx: number | null): PopStateOutcome {
      const at = currentIdx === null ? -1 : moves.findIndex((m) => m.target === currentIdx)
      if (at !== -1) {
        const [move] = moves.splice(at, 1)
        settle(move)
        // One deferred unwind per popstate: each runs against the cursor the move before it left,
        // and queues its own `expectSelfPop`, so a third waits for the second's popstate in turn.
        afterSelfPop.shift()?.()
        return "self"
      }

      const top = entries[entries.length - 1]
      let outcome: PopStateOutcome = "none"
      if (top) {
        const action = nextDialogHistoryAction({
          event: "popstate",
          dismissible: top.isDismissible(),
          hasEntry: true,
        })
        if (action === "closeOnly") {
          top.close()
          outcome = "closeOnly"
        } else if (action === "repush") {
          top.repush()
          outcome = "repush"
        }
      }
      // A real Back with no move of ours outstanding: nothing is going to settle the cursor for work that
      // is waiting on it (its trigger, the overlay above, has just gone), so release one waiting unwind now.
      if (moves.length === 0) afterSelfPop.shift()?.()
      return outcome
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
