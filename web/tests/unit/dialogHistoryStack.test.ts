import { beforeEach, describe, expect, it, vi } from "vitest"
import { createDialogHistoryStack } from "@/lib/nav/dialogHistoryStack"

/*
 * `popstate` is a window-level event, so every mounted overlay's listener
 * hears every back press. Before this stack existed, a `ConfirmModal` opened
 * over a `Modal` had two listeners answering one back press: both closed, and
 * the destructive confirmation vanished along with the dialog that raised it
 * while one of the two pushed entries stayed in the history. The stack makes
 * "which overlay does this back press belong to?" a single, ordered decision.
 */

function overlay(dismissible: boolean) {
  return {
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

  it("reports how many overlays hold a history entry", () => {
    expect(stack.size).toBe(0)
    const release = stack.register(overlay(true))
    expect(stack.size).toBe(1)
    release()
    expect(stack.size).toBe(0)
  })
})
