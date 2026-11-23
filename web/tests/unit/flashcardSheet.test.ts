// FcSheet is a Radix dialog and node has no DOM, so it is called as a function and the element it
// returns is read, the way deckSheets.test.ts reads the sheets' own trees.
import { createElement } from "react"
import { describe, expect, it } from "vitest"
import { ALERT_BODY_ID, FcSheet } from "@/portals/student/screens/flashcards/parts/FcSheet"

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
})
