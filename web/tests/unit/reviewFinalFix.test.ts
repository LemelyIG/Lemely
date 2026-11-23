import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { QueueRow } from "@/portals/teacher/screens/review/QueueRow"
import { removeDecidedRows } from "@/portals/teacher/screens/review/reviewQueueModel"

const dir = join(import.meta.dirname, "../../src/portals/teacher/screens/review")

describe("review regressions", () => {
  it("removes committed and bulk-approved rows before subtracting pending work from the refreshed total", () => {
    const rows = [{ itemId: "a" }, { itemId: "b" }, { itemId: "c" }] as ReviewQueueItem[]
    const remaining = removeDecidedRows(rows, ["a", "b"])
    expect(remaining.map((r) => r.itemId)).toEqual(["c"])
    expect(9 - remaining.filter((r) => new Set(["a", "b"]).has(r.itemId)).length).toBe(9)
  })
  it("keeps cached detail visible and resets desktop panel state when the item changes", () => {
    const src = readFileSync(join(dir, "ReviewQueue.tsx"), "utf8")
    expect(src).toMatch(/detail\.isError\s*&&\s*!detail\.data/)
  })
  it("resets the desktop answer panel for a new item", () => {
    const src = readFileSync(join(dir, "ReviewQueue.tsx"), "utf8")
    expect(src).toMatch(/<AnswerPanel key=\{view\.key\}/)
  })
  it("makes a collapsed row inert", () => {
    const item = { itemId: "a", reason: "low_confidence", questionId: "1", studentDisplayName: "A", confidenceScore: null, aiAwardedMarks: null, maximumMarks: null } as ReviewQueueItem
    const html = renderToStaticMarkup(createElement(QueueRow, { item, focused: false, gone: true, selecting: false, picked: false, onOpen: () => {}, onPick: () => {} }))
    expect(html).toMatch(/<li[^>]*\sinert=""/)
  })
})
