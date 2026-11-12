import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { nextDialogHistoryAction } from "@/lib/nav/dialogHistory"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B2a · the pure decision table behind `useDialogHistory`. Every
 * `Modal`/`NavDrawer` open pushes one history entry so browser back closes
 * the overlay instead of navigating away; `ConfirmModal` (`dismissible:
 * false`) re-pushes instead of closing, since a stray back gesture must not
 * silently answer a destructive confirmation.
 */

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

function read(relPath: string): string {
  return stripComments(readFileSync(join(SRC, relPath), "utf8"))
}

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

describe("useDialogHistory's own history push does not reset scroll", () => {
  // A dialog's opening push is a same-URL bookkeeping entry, not real
  // navigation — but `<ScrollRestoration>` cannot tell the difference from
  // `scrollRestorationKey`'s POV on a non-tab-root screen, since a push keys
  // by `location.key`, which changes on every push including this one. Left
  // unguarded, opening a dialog scrolls the page to the top. `preventScrollReset:
  // true` on this specific `navigate()` call is what stops that, without
  // touching PUSH-resets-to-top behaviour for real navigation elsewhere.
  const source = read("lib/nav/useDialogHistory.ts")
  const pushBlock = source.match(/if \(action === "push"\) \{[\s\S]*?\n {4}\}/)

  it("has a push branch to inspect (source shape sanity check)", () => {
    expect(pushBlock).not.toBeNull()
  })

  it("the push branch's navigate() call passes preventScrollReset: true", () => {
    const navigateCall = pushBlock?.[0].match(/navigate\(location, \{[\s\S]*?\n\s*\}\)/)
    expect(navigateCall).not.toBeNull()
    expect(navigateCall?.[0]).toMatch(/preventScrollReset:\s*true/)
  })
})
