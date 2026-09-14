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
}

export type PopStateOutcome = "self" | "none" | "closeOnly" | "repush"

export function createDialogHistoryStack() {
  const entries: DialogHistoryEntry[] = []
  let pendingSelfPops = 0

  return {
    /** Call when an overlay has pushed its history entry. Returns the release. */
    register(entry: DialogHistoryEntry): () => void {
      entries.push(entry)
      return () => {
        const at = entries.lastIndexOf(entry)
        if (at !== -1) entries.splice(at, 1)
      }
    },

    /** Call immediately before moving the history cursor ourselves. */
    expectSelfPop(): void {
      pendingSelfPops += 1
    },

    handlePopState(): PopStateOutcome {
      if (pendingSelfPops > 0) {
        pendingSelfPops -= 1
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

    get size(): number {
      return entries.length
    },
  }
}

export const dialogHistoryStack = createDialogHistoryStack()
