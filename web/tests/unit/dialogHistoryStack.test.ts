import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { SELF_POP_GIVE_UP_MS, createDialogHistoryStack } from "@/lib/nav/dialogHistoryStack"

/*
 * `popstate` is a window-level event, so every mounted overlay's listener
 * hears every back press. Before this stack existed, a `ConfirmModal` opened
 * over a `Modal` had two listeners answering one back press: both closed, and
 * the destructive confirmation vanished along with the dialog that raised it
 * while one of the two pushed entries stayed in the history. The stack makes
 * "which overlay does this back press belong to?" a single, ordered decision.
 */

function overlay(dismissible: boolean, current = false) {
  return {
    isCurrent: () => current,
    isDismissible: () => dismissible,
    close: vi.fn(),
    repush: vi.fn(),
  }
}

describe("createDialogHistoryStack", () => {
  let stack: ReturnType<typeof createDialogHistoryStack>

  beforeEach(() => {
    stack = createDialogHistoryStack()
  })

  it("a back press with nothing open is not this stack's to answer", () => {
    expect(stack.handlePopState(0)).toBe("none")
  })

  it("a lone dismissible overlay closes on a back press", () => {
    const modal = overlay(true)
    stack.register(modal)

    expect(stack.handlePopState(9)).toBe("closeOnly")
    expect(modal.close).toHaveBeenCalledTimes(1)
  })

  it("only the topmost overlay answers a back press", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    stack.register(modal)
    stack.register(confirm)

    stack.handlePopState(9)

    expect(confirm.close).toHaveBeenCalledTimes(1)
    expect(modal.close).not.toHaveBeenCalled()
  })

  it("a non-dismissible top re-pushes without disturbing the overlay beneath it", () => {
    const modal = overlay(true)
    const confirm = overlay(false)
    stack.register(modal)
    stack.register(confirm)

    expect(stack.handlePopState(9)).toBe("repush")
    expect(confirm.repush).toHaveBeenCalledTimes(1)
    expect(modal.close).not.toHaveBeenCalled()
    expect(modal.repush).not.toHaveBeenCalled()
  })

  it("once the top has unregistered, the next back press reaches the one below", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    stack.register(modal)
    const releaseConfirm = stack.register(confirm)

    releaseConfirm()
    stack.handlePopState(9)

    expect(modal.close).toHaveBeenCalledTimes(1)
    expect(confirm.close).not.toHaveBeenCalled()
  })

  it("releasing an entry twice does not disturb the rest of the stack", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    const releaseModal = stack.register(modal)
    stack.register(confirm)

    releaseModal()
    releaseModal()

    expect(stack.size).toBe(1)
    stack.handlePopState(3)
    expect(confirm.close).toHaveBeenCalledTimes(1)
  })

  it("a self-initiated history move is swallowed rather than answered", () => {
    const modal = overlay(true)
    stack.register(modal)

    stack.expectSelfPop(4)

    expect(stack.handlePopState(4)).toBe("self")
    expect(modal.close).not.toHaveBeenCalled()
  })

  it("each self-initiated move is swallowed exactly once", () => {
    const modal = overlay(true)
    stack.register(modal)

    stack.expectSelfPop(4)
    stack.handlePopState(4)

    expect(stack.handlePopState(4)).toBe("closeOnly")
    expect(modal.close).toHaveBeenCalledTimes(1)
  })

  it("a popstate that lands anywhere but a move's target is a real Back, even with a move in flight", () => {
    const modal = overlay(true)
    stack.register(modal)

    stack.expectSelfPop(4)

    expect(stack.handlePopState(7)).toBe("closeOnly")
    expect(modal.close).toHaveBeenCalledTimes(1)
    // The move of ours is still expected, and is still ours when it lands.
    expect(stack.hasPendingSelfPop()).toBe(true)
    expect(stack.handlePopState(4)).toBe("self")
  })

  it("two overlays unwinding at once each swallow their own move", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    stack.register(modal)
    stack.register(confirm)

    stack.expectSelfPop(5)
    stack.expectSelfPop(4)

    expect(stack.handlePopState(5)).toBe("self")
    expect(stack.handlePopState(4)).toBe("self")
    expect(modal.close).not.toHaveBeenCalled()
    expect(confirm.close).not.toHaveBeenCalled()
  })

  it("a move's own callback runs once when it lands", () => {
    const landed = vi.fn()
    stack.expectSelfPop(4, landed)
    expect(landed).not.toHaveBeenCalled()
    stack.handlePopState(4)
    expect(landed).toHaveBeenCalledTimes(1)
    stack.handlePopState(4)
    expect(landed).toHaveBeenCalledTimes(1)
  })

  it("a deferred unwind runs on the popstate of the move in flight, once", () => {
    stack.expectSelfPop(4)
    expect(stack.hasPendingSelfPop()).toBe(true)
    const second = vi.fn()
    stack.afterNextSelfPop(second)
    expect(second).not.toHaveBeenCalled()

    expect(stack.handlePopState(4)).toBe("self")
    expect(second).toHaveBeenCalledTimes(1)
    expect(stack.hasPendingSelfPop()).toBe(false)

    stack.expectSelfPop(3)
    stack.handlePopState(3)
    expect(second).toHaveBeenCalledTimes(1)
  })

  it("stacked unwinds run one per popstate, each queueing the next move", () => {
    const order: string[] = []
    stack.expectSelfPop(5) // overlay B's navigate(-1) is in flight
    stack.afterNextSelfPop(() => {
      order.push("A")
      stack.expectSelfPop(4)
    })
    expect(stack.handlePopState(5)).toBe("self")
    expect(order).toEqual(["A"])
    expect(stack.hasPendingSelfPop()).toBe(true)
    expect(stack.handlePopState(4)).toBe("self")
    expect(stack.hasPendingSelfPop()).toBe(false)
  })

  it("an unwind queued behind an overlay that real Back then closes runs on that Back", () => {
    const upper = overlay(true)
    stack.register(upper)
    const lowerUnwind = vi.fn()
    stack.afterNextSelfPop(lowerUnwind) // the lower overlay closed under the open upper one

    expect(stack.handlePopState(5)).toBe("closeOnly")

    expect(upper.close).toHaveBeenCalledTimes(1)
    expect(lowerUnwind).toHaveBeenCalledTimes(1)
    expect(stack.hasPendingWork()).toBe(false)
  })

  it("a real Back does not release a queued unwind while a move of ours is still in flight", () => {
    const waiting = vi.fn()
    stack.expectSelfPop(4)
    stack.afterNextSelfPop(waiting)

    stack.handlePopState(9)

    expect(waiting).not.toHaveBeenCalled()
  })

  it("reports how many overlays hold a history entry", () => {
    expect(stack.size).toBe(0)
    const release = stack.register(overlay(true))
    expect(stack.size).toBe(1)
    release()
    expect(stack.size).toBe(0)
  })

  it("topEntryIsCurrent reads the top-most overlay only", () => {
    const stack = createDialogHistoryStack()
    expect(stack.topEntryIsCurrent()).toBe(false)
    stack.register(overlay(true, true))
    expect(stack.topEntryIsCurrent()).toBe(true)
    const releaseTop = stack.register(overlay(true, false))
    expect(stack.topEntryIsCurrent()).toBe(false)
    releaseTop()
    expect(stack.topEntryIsCurrent()).toBe(true)
  })
})

describe("a late popstate and a lost one", () => {
  afterEach(() => vi.useRealTimers())

  it("a move that lands long after the old one-second window is still ours", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    const modal = overlay(true)
    stack.register(modal)
    stack.expectSelfPop(4)
    vi.advanceTimersByTime(1500)
    expect(stack.hasPendingSelfPop()).toBe(true)
    expect(stack.handlePopState(4)).toBe("self")
    expect(modal.close).not.toHaveBeenCalled()
  })

  it("gives up on a move that never reports, so the in-flight record cannot stay stuck", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    stack.expectSelfPop(4)
    expect(stack.hasPendingSelfPop()).toBe(true)
    vi.advanceTimersByTime(SELF_POP_GIVE_UP_MS + 10)
    expect(stack.hasPendingSelfPop()).toBe(false)
  })

  it("runs the callback and the unwind waiting on the lost move, once, when it is given up on", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    const waiting = vi.fn()
    const landed = vi.fn()
    stack.expectSelfPop(4, landed)
    stack.afterNextSelfPop(waiting)
    expect(stack.hasPendingWork()).toBe(true)
    vi.advanceTimersByTime(SELF_POP_GIVE_UP_MS + 10)
    expect(landed).toHaveBeenCalledTimes(1)
    expect(waiting).toHaveBeenCalledTimes(1)
    expect(stack.hasPendingWork()).toBe(false)
  })

  it("a move that does land cancels its own give-up", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    const landed = vi.fn()
    stack.expectSelfPop(4, landed)
    stack.handlePopState(4)
    vi.advanceTimersByTime(SELF_POP_GIVE_UP_MS + 10)
    expect(landed).toHaveBeenCalledTimes(1)
  })
})

describe("wiring (polish B, item 18)", () => {
  const read = (rel: string) => readFileSync(join(import.meta.dirname, "..", "..", "src", rel), "utf8")

  it("useDialogHistory defers an unwind while another overlay's move is still in flight", () => {
    const hook = read("lib/nav/useDialogHistory.ts")
    const unwind = hook.slice(hook.indexOf("function unwindEntry"), hook.indexOf("const unwindRef"))
    expect(unwind).toContain("dialogHistoryStack.hasPendingSelfPop()")
    expect(unwind).toContain("isDialogEntry(window.history.state, pushedIdx, pushedId)")
    expect(unwind).toContain("dialogHistoryStack.afterNextSelfPop(unwind)")
  })

  it("the window listener stays up while a move of ours is in flight, and the move restarts it", () => {
    const hook = read("lib/nav/useDialogHistory.ts")
    expect(hook).toContain("dialogHistoryStack.hasPendingWork()")
    expect(hook).toMatch(/startListening\(\)\s*\n\s*dialogHistoryStack\.expectSelfPop\(pushedIdx - 1, settleUnwind\)/)
    expect(hook).toMatch(/function onWindowPopState\(\) \{[\s\S]*?stopListeningIfIdle\(\)/)
  })

  it("Popover never reads the DOM during render to name its sheet", () => {
    const popover = read("components/ui/popover.tsx")
    expect(popover).not.toContain("document.getElementById")
    expect(popover).toContain("triggerRef.current?.id === triggerId")
  })
})
