import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * C2 (Tasks 3-4). Every hand-rolled `<table>` under `src/portals/teacher`
 * migrates onto the `Table`/`THead`/`TBody`/`TR`/`TH`/`TD` primitive
 * (`table.tsx`, Task 2) at `density="operate"` — the tighter cell rhythm
 * those screens already reached for as the `px-[16px] py-[10px]` arbitrary
 * value DESIGN.md §14 rule 3 forbids, now on the scale via `CELL_PADDING`.
 *
 * Task 3 (C2a) covers `Review.tsx` and `ClassRoster.tsx`. Task 4 (C2b)
 * extends `FILES` below with `StudentDetail.tsx`, `AtRiskList.tsx`,
 * `ClassAnalytics.tsx`, `Classes.tsx`, `MarkSchemes.tsx`, and the real-count
 * correction's `QuizResults.tsx`/`Quizzes.tsx` — the array shape is what
 * makes that extension a one-line addition per file rather than a new
 * describe block.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")
const SCREENS_DIR = path.join(ROOT, "src", "portals", "teacher", "screens")

interface FileCheck {
  file: string
  /** Substrings the migrated source must contain. */
  mustContain: string[]
  /** Substrings the migrated source must no longer contain. */
  mustNotContain: string[]
}

const FILES: FileCheck[] = [
  {
    file: "Review.tsx",
    mustContain: ['<Table density="operate"'],
    mustNotContain: ["<table", "px-[16px]", "py-[10px]"],
  },
  {
    file: "ClassRoster.tsx",
    mustContain: ['<Table density="operate"'],
    mustNotContain: ["<table", "px-[16px]", "py-[10px]"],
  },
  {
    file: "StudentDetail.tsx",
    mustContain: ['<Table density="operate"'],
    mustNotContain: ["<table", "px-[16px]", "py-[10px]"],
  },
  {
    file: "AtRiskList.tsx",
    mustContain: ['<Table density="operate"'],
    mustNotContain: ["<table", "px-[16px]", "py-[10px]"],
  },
  {
    file: "Classes.tsx",
    mustContain: ['<Table density="operate"'],
    mustNotContain: ["<table", "px-[16px]", "py-[10px]"],
  },
]

function sourceOf(file: string): string {
  return stripComments(fs.readFileSync(path.join(SCREENS_DIR, file), "utf8"))
}

describe("teacher screens render tables through the Table primitive", () => {
  for (const { file, mustContain, mustNotContain } of FILES) {
    describe(file, () => {
      const source = sourceOf(file)

      for (const needle of mustContain) {
        it(`contains ${JSON.stringify(needle)}`, () => {
          expect(source).toContain(needle)
        })
      }

      for (const needle of mustNotContain) {
        it(`no longer contains ${JSON.stringify(needle)}`, () => {
          expect(source).not.toContain(needle)
        })
      }
    })
  }
})
