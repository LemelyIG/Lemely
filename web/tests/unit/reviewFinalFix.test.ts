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
  it("drops decided rows so they stop counting against the hidden subtraction", () => {
    const rows = [{ itemId: "a" }, { itemId: "b" }, { itemId: "c" }] as ReviewQueueItem[]
    const hidden = new Set(["a", "b"])
    const hiddenCount = (list: ReviewQueueItem[]) => list.filter((r) => hidden.has(r.itemId)).length
    // Before removal the two decided rows are still listed, so they would be subtracted from the total.
    expect(hiddenCount(rows)).toBe(2)
    const remaining = removeDecidedRows(rows, ["a", "b"])
    expect(remaining.map((r) => r.itemId)).toEqual(["c"])
    // After removal nothing is left to subtract, so a refreshed server total of 9 is not reduced again.
    expect(hiddenCount(remaining)).toBe(0)
  })
  it("wires removeDecidedRows into both the committed-decision and bulk-approve setPages updaters", () => {
    const src = readFileSync(join(dir, "ReviewQueue.tsx"), "utf8")
    // Committed decision (usePendingDecisions onCommit): removes the single decided item.
    expect(src).toMatch(/setPages\(\(prev\) => \(\{ \.\.\.prev, items: removeDecidedRows\(prev\.items, \[d\.itemId\]\) \}\)\)/)
    // Bulk approve (onSuccess): removes every approved id.
    expect(src).toMatch(/setPages\(\(prev\) => \(\{ \.\.\.prev, items: removeDecidedRows\(prev\.items, res\.approved\) \}\)\)/)
    expect(src.match(/removeDecidedRows\(prev\.items,/g)).toHaveLength(2)
  })
  it("subtracts only still-listed hidden rows from the server total", () => {
    const src = readFileSync(join(dir, "ReviewQueue.tsx"), "utf8")
    expect(src).toMatch(/const total = Math\.max\(0, \(load\.page\?\.total \?\? 0\) - rows\.filter\(\(r\) => hidden\.has\(r\.itemId\)\)\.length\)/)
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
