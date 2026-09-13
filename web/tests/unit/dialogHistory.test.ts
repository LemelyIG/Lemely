import { describe, expect, it } from "vitest"
import { nextDialogHistoryAction } from "@/lib/nav/dialogHistory"

/*
 * Packet B2a · the pure decision table behind `useDialogHistory`. Every
 * `Modal`/`NavDrawer` open pushes one history entry so browser back closes
 * the overlay instead of navigating away; `ConfirmModal` (`dismissible:
 * false`) re-pushes instead of closing, since a stray back gesture must not
 * silently answer a destructive confirmation.
 */

describe("nextDialogHistoryAction", () => {
  it("open + no entry yet (dismissible) pushes a history entry", () => {
    expect(
      nextDialogHistoryAction({ event: "open", dismissible: true, hasEntry: false }),
    ).toBe("push")
  })

  it("open + no entry yet (not dismissible) also pushes — ConfirmModal still needs the entry", () => {
    expect(
      nextDialogHistoryAction({ event: "open", dismissible: false, hasEntry: false }),
    ).toBe("push")
  })

  it("open while an entry already exists does nothing (re-render, not a re-open)", () => {
    expect(
      nextDialogHistoryAction({ event: "open", dismissible: true, hasEntry: true }),
    ).toBe("none")
  })

  it("programmatic close with an entry pending unwinds it", () => {
    expect(
      nextDialogHistoryAction({ event: "close", dismissible: true, hasEntry: true }),
    ).toBe("pop")
    expect(
      nextDialogHistoryAction({ event: "close", dismissible: false, hasEntry: true }),
    ).toBe("pop")
  })

  it("close with no entry pending does nothing", () => {
    expect(
      nextDialogHistoryAction({ event: "close", dismissible: true, hasEntry: false }),
    ).toBe("none")
  })

  it("browser back on a dismissible overlay closes it only (no further navigation)", () => {
    expect(
      nextDialogHistoryAction({ event: "popstate", dismissible: true, hasEntry: true }),
    ).toBe("closeOnly")
  })

  it("browser back on a non-dismissible overlay (ConfirmModal) re-pushes the entry", () => {
    expect(
      nextDialogHistoryAction({ event: "popstate", dismissible: false, hasEntry: true }),
    ).toBe("repush")
  })

  it("popstate with no entry pending does nothing — not this dialog's history entry", () => {
    expect(
      nextDialogHistoryAction({ event: "popstate", dismissible: true, hasEntry: false }),
    ).toBe("none")
    expect(
      nextDialogHistoryAction({ event: "popstate", dismissible: false, hasEntry: false }),
    ).toBe("none")
  })
})
