import { describe, expect, it } from "vitest"
import type { BinnyMood } from "@/components/redesign"
import type { HomeMoment, PaperMoment } from "@/lib/studentHomeTypes"
import { pickStage } from "@/portals/student/home/model"
import { makeHome } from "./studentHomeFixture"

/*
 * Owner decision 2026-11-24: Binny's mood scales with the grade. The lower the grade, the sadder, always
 * using the poses that already exist (happy, wink, open, thinking, sad) and never new art.
 */

const NONE: ReadonlySet<string> = new Set()
const SADDEST_FIRST: readonly BinnyMood[] = ["sad", "thinking", "open", "wink", "happy"]
const LADDER_BEST_FIRST = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"] as const

const base: PaperMoment = {
  kind: "result", paperId: "5", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4,
  awarded: 61, maximum: 80, grade: "B", previousGrade: null, focusQuestion: "8", recordedAt: "2026-11-12T07:00:00+00:00",
}

function stageFor(over: Partial<PaperMoment>) {
  return pickStage(makeHome({ moments: [{ ...base, ...over } as HomeMoment] }), NONE)
}

describe("Binny's mood follows the grade", () => {
  it.each([
    ["A*", "happy", "hop"],
    ["A", "happy", "hop"],
    ["B", "wink", "idle"],
    ["C", "open", "idle"],
    ["D", "thinking", "idle"],
    ["E", "sad", "idle"],
    ["F", "sad", "idle"],
    ["G", "sad", "idle"],
    ["U", "sad", "idle"],
  ] as const)("a first %s result: %s, %s", (grade, mood, motion) => {
    expect(stageFor({ grade })).toMatchObject({ kind: "result", mood, motion })
  })

  it("never gets happier as the grade falls", () => {
    const rank = LADDER_BEST_FIRST.map((grade) => SADDEST_FIRST.indexOf(stageFor({ grade }).mood))
    for (let i = 1; i < rank.length; i++) {
      expect(rank[i], `${LADDER_BEST_FIRST[i]} vs ${LADDER_BEST_FIRST[i - 1]}`).toBeLessThanOrEqual(rank[i - 1]!)
    }
    expect(rank[0]).toBe(SADDEST_FIRST.indexOf("happy"))
    expect(rank[rank.length - 1]).toBe(SADDEST_FIRST.indexOf("sad"))
  })

  it("only a happy Binny hops, so a low grade never gets a celebration", () => {
    for (const grade of LADDER_BEST_FIRST) {
      const s = stageFor({ grade })
      expect(s.motion, grade).toBe(s.mood === "happy" ? "hop" : "idle")
    }
  })

  it("a drop does not keep Binny happy and hopping: From A to C", () => {
    const s = stageFor({ grade: "C", previousGrade: "A" })
    expect(s.line).toBe("From A to C")
    expect(s.mood).not.toBe("happy")
    expect(s.motion).toBe("idle")
  })

  it("From A* to A is still an A: happy and hopping, even though the grade dropped", () => {
    expect(stageFor({ grade: "A", previousGrade: "A*" })).toMatchObject({ line: "From A* to A", mood: "happy", motion: "hop" })
  })

  it("a rise keeps the grade's own mood: From C to B is a pleased Binny, not a hopping one", () => {
    expect(stageFor({ grade: "B", previousGrade: "C" })).toMatchObject({ line: "From C to B", mood: "wink", motion: "idle" })
    expect(stageFor({ grade: "A", previousGrade: "C" })).toMatchObject({ line: "From C to A", mood: "happy", motion: "hop" })
  })

  it("the same grade gives the same mood whatever the previous grade or the paper kind", () => {
    for (const grade of [...LADDER_BEST_FIRST, "9", ""]) {
      const alone = stageFor({ grade, previousGrade: null }).mood
      for (const previousGrade of [null, ...LADDER_BEST_FIRST]) {
        for (const kind of ["result", "tough"] as const) {
          expect(stageFor({ kind, grade, previousGrade }).mood, `${kind} ${previousGrade}->${grade}`).toBe(alone)
        }
      }
    }
  })

  it("a tough paper takes its grade's mood: a tough C is open, a tough E is sad", () => {
    expect(stageFor({ kind: "tough", grade: "C", previousGrade: "B" }).mood).toBe("open")
    expect(stageFor({ kind: "tough", grade: "D", previousGrade: null }).mood).toBe("thinking")
    expect(stageFor({ kind: "tough", grade: "E", previousGrade: null }).mood).toBe("sad")
    expect(stageFor({ kind: "tough", grade: "U", previousGrade: "C" }).mood).toBe("sad")
  })

  it("a grade off the ladder makes no claim: neutral Binny, no hop", () => {
    expect(stageFor({ grade: "9" })).toMatchObject({ mood: "open", motion: "idle" })
    expect(stageFor({ grade: "" })).toMatchObject({ mood: "open", motion: "idle" })
  })
})
