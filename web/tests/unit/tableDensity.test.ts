import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"
import { CELL_PADDING } from "@/components/ui/table"

/*
 * C1b (Task 2). `CELL_PADDING` codifies the two cell rhythms the product
 * actually uses: `comfortable` (the kit's existing `px-4 py-3`, unchanged —
 * six admin/marketing tables already render at this density and must keep
 * doing so) and `operate` (the `px-4 py-2.5` rhythm every hand-rolled teacher
 * table on this branch already reaches for by literal, on the scale rather
 * than as a `px-[16px] py-[10px]` arbitrary value — DESIGN.md §14 rule 3).
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("CELL_PADDING", () => {
  it("comfortable keeps the kit's existing px-4 py-3 rhythm", () => {
    expect(CELL_PADDING.comfortable).toBe("px-4 py-3")
  })

  it("operate matches the 16px/10px rhythm every hand-rolled teacher table used", () => {
    expect(CELL_PADDING.operate).toBe("px-4 py-2.5")
  })
})

describe("table.tsx density plumbing (source)", () => {
  const source = sourceOf("src/components/ui/table.tsx")

  it("provides a TableDensityContext so TH/TD read density without threading a prop through every cell", () => {
    expect(source).toContain("TableDensityContext")
  })

  it("carries no px-4 py-3 literal outside CELL_PADDING's own definition", () => {
    const occurrences = source.split("px-4 py-3").length - 1
    expect(occurrences).toBe(1)
  })
})
