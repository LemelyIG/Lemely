// FcSheet is a Radix dialog and node has no DOM, so it is called as a function and the element it
// returns is read, the way deckSheets.test.ts reads the sheets' own trees.
import { createElement } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ALERT_BODY_ID, FcSheet } from "@/portals/student/screens/flashcards/parts/FcSheet"

// Browser back must close every flashcards sheet, so FcSheet registers the shared dialog-history hook.
const { useDialogHistory } = vi.hoisted(() => ({ useDialogHistory: vi.fn() }))
vi.mock("@/lib/nav/useDialogHistory", () => ({ useDialogHistory }))

type El = { type: unknown; props: Record<string, unknown> }
function findAll(node: unknown, match: (el: El) => boolean, found: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => findAll(n, match, found))
  else if (node && typeof node === "object" && "props" in node) {
    const el = node as El
    if (match(el)) found.push(el)
    findAll(el.props.children, match, found)
  }
  return found
}

function content(alert: boolean): El {
  const tree = FcSheet({ open: true, onOpenChange: () => {}, title: "Delete deck?", alert, children: createElement("p") })
  const found = findAll(tree, (el) => "role" in el.props)[0]
  if (!found) throw new Error("no sheet content")
  return found
}

describe("FcSheet", () => {
  it("an alert sheet is an alertdialog described by its consequence paragraph", () => {
    const sheet = content(true)
    expect(sheet.props.role).toBe("alertdialog")
    expect(sheet.props["aria-describedby"]).toBe(ALERT_BODY_ID)
  })

  it("a plain sheet is a dialog with no description to point at", () => {
    const sheet = content(false)
    expect(sheet.props.role).toBe("dialog")
    expect(sheet.props["aria-describedby"]).toBeUndefined()
  })

  describe("browser history", () => {
    beforeEach(() => useDialogHistory.mockClear())

    it("registers every sheet as dismissible, so browser back closes it", () => {
      FcSheet({ open: true, onOpenChange: () => {}, title: "Rename deck", children: createElement("p") })
      expect(useDialogHistory).toHaveBeenCalledTimes(1)
      expect(useDialogHistory.mock.calls[0][0]).toMatchObject({ open: true, dismissible: true })
    })

    it("a back press closes the sheet through onOpenChange, not by leaving the page", () => {
      const onOpenChange = vi.fn()
      FcSheet({ open: true, onOpenChange, title: "Delete deck?", alert: true, children: createElement("p") })
      useDialogHistory.mock.calls[0][0].onClose()
      expect(onOpenChange).toHaveBeenCalledWith(false)
    })

    it("a sheet whose action is in flight is not dismissible, so Back re-pushes instead of leaving the page", () => {
      FcSheet({ open: true, onOpenChange: () => {}, title: "Delete deck?", alert: true, dismissible: false, children: createElement("p") })
      expect(useDialogHistory.mock.calls[0][0]).toMatchObject({ open: true, dismissible: false })
    })
  })
})
