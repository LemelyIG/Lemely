import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { SELF_POP_EXPIRY_MS, createDialogHistoryStack } from "@/lib/nav/dialogHistoryStack"

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
    expect(stack.handlePopState()).toBe("none")
  })

  it("a lone dismissible overlay closes on a back press", () => {
    const modal = overlay(true)
    stack.register(modal)

    expect(stack.handlePopState()).toBe("closeOnly")
    expect(modal.close).toHaveBeenCalledTimes(1)
  })

  it("only the topmost overlay answers a back press", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    stack.register(modal)
    stack.register(confirm)

    stack.handlePopState()

    expect(confirm.close).toHaveBeenCalledTimes(1)
    expect(modal.close).not.toHaveBeenCalled()
  })

  it("a non-dismissible top re-pushes without disturbing the overlay beneath it", () => {
    const modal = overlay(true)
    const confirm = overlay(false)
    stack.register(modal)
    stack.register(confirm)

    expect(stack.handlePopState()).toBe("repush")
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
    stack.handlePopState()

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
    stack.handlePopState()
    expect(confirm.close).toHaveBeenCalledTimes(1)
  })

  it("a self-initiated history move is swallowed rather than answered", () => {
    const modal = overlay(true)
    stack.register(modal)

    stack.expectSelfPop()

    expect(stack.handlePopState()).toBe("self")
    expect(modal.close).not.toHaveBeenCalled()
  })

  it("each self-initiated move is swallowed exactly once", () => {
    const modal = overlay(true)
    stack.register(modal)

    stack.expectSelfPop()
    stack.handlePopState()

    expect(stack.handlePopState()).toBe("closeOnly")
    expect(modal.close).toHaveBeenCalledTimes(1)
  })

  it("two overlays unwinding at once each swallow their own move", () => {
    const modal = overlay(true)
    const confirm = overlay(true)
    stack.register(modal)
    stack.register(confirm)

    stack.expectSelfPop()
    stack.expectSelfPop()

    expect(stack.handlePopState()).toBe("self")
    expect(stack.handlePopState()).toBe("self")
    expect(modal.close).not.toHaveBeenCalled()
    expect(confirm.close).not.toHaveBeenCalled()
  })

  it("a deferred unwind runs on the popstate of the move in flight, once", () => {
    stack.expectSelfPop()
    expect(stack.hasPendingSelfPop()).toBe(true)
    const second = vi.fn()
    stack.afterNextSelfPop(second)
    expect(second).not.toHaveBeenCalled()

    expect(stack.handlePopState()).toBe("self")
    expect(second).toHaveBeenCalledTimes(1)
    expect(stack.hasPendingSelfPop()).toBe(false)

    stack.expectSelfPop()
    stack.handlePopState()
    expect(second).toHaveBeenCalledTimes(1)
  })

  it("stacked unwinds run one per popstate, each queueing the next move", () => {
    const order: string[] = []
    stack.expectSelfPop() // overlay B's navigate(-1) is in flight
    stack.afterNextSelfPop(() => {
      order.push("A")
      stack.expectSelfPop()
    })
    expect(stack.handlePopState()).toBe("self")
    expect(order).toEqual(["A"])
    expect(stack.hasPendingSelfPop()).toBe(true)
    expect(stack.handlePopState()).toBe("self")
    expect(stack.hasPendingSelfPop()).toBe(false)
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

describe("a move whose popstate never arrives (fix round 1)", () => {
  afterEach(() => vi.useRealTimers())

  it("expires, so the in-flight count cannot stay stuck and starve later unwinds", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    stack.expectSelfPop()
    expect(stack.hasPendingSelfPop()).toBe(true)
    vi.advanceTimersByTime(SELF_POP_EXPIRY_MS + 10)
    expect(stack.hasPendingSelfPop()).toBe(false)
  })

  it("runs the unwind waiting on the lost move, once, when it expires", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    const waiting = vi.fn()
    stack.expectSelfPop()
    stack.afterNextSelfPop(waiting)
    expect(stack.hasPendingWork()).toBe(true)
    vi.advanceTimersByTime(SELF_POP_EXPIRY_MS + 10)
    expect(waiting).toHaveBeenCalledTimes(1)
    expect(stack.hasPendingWork()).toBe(false)
  })

  it("a move that does land cancels its own expiry", () => {
    vi.useFakeTimers()
    const stack = createDialogHistoryStack()
    stack.expectSelfPop()
    stack.handlePopState()
    stack.expectSelfPop()
    vi.advanceTimersByTime(SELF_POP_EXPIRY_MS - 100)
    expect(stack.hasPendingSelfPop()).toBe(true)
  })
})

describe("wiring (polish B, item 18)", () => {
  const read = (rel: string) => readFileSync(join(import.meta.dirname, "..", "..", "src", rel), "utf8")

  it("useDialogHistory defers an unwind while another overlay's move is still in flight", () => {
    const hook = read("lib/nav/useDialogHistory.ts")
    const unwind = hook.slice(hook.indexOf("function unwindEntry"), hook.indexOf("const unwindRef"))
    expect(unwind).toContain("dialogHistoryStack.hasPendingSelfPop()")
    expect(unwind).toContain("dialogHistoryStack.afterNextSelfPop(unwind)")
  })

  it("the window listener stays up while a move of ours is in flight, and the move restarts it", () => {
    const hook = read("lib/nav/useDialogHistory.ts")
    expect(hook).toContain("dialogHistoryStack.hasPendingWork()")
    expect(hook).toMatch(/startListening\(\)\s*\n\s*dialogHistoryStack\.expectSelfPop\(\)/)
    expect(hook).toMatch(/function onWindowPopState\(\) \{[\s\S]*?stopListeningIfIdle\(\)/)
  })

  it("Popover never reads the DOM during render to name its sheet", () => {
    const popover = read("components/ui/popover.tsx")
    expect(popover).not.toContain("document.getElementById")
    expect(popover).toContain("triggerRef.current?.id === triggerId")
  })
})
