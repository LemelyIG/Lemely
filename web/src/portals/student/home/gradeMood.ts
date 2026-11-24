/*
 * Binny's mood for a marked paper. Pure. Owner decision 2026-11-24: the lower the grade, the sadder Binny gets,
 * encouraging and never shaming. Only the poses the Binny component already draws are used (happy, wink, open,
 * thinking, sad); nothing here asks for new art. Motion stays with `motionFor` in model.ts: only a happy Binny hops.
 *
 *   A*, A  happy      B  wink      C  open      D  thinking      E, F, G, U  sad
 *
 * A paper the server calls tough, or any drop in grade, is never happier than `thinking`, so a hopping Binny
 * never sits beside "Win back easy marks" or "From A to C". A grade off this ladder makes no claim: `open`.
 */
import type { BinnyMood } from "@/components/redesign"

const LADDER = ["U", "G", "F", "E", "D", "C", "B", "A", "A*"] as const

const MOOD_BY_GRADE: Record<(typeof LADDER)[number], BinnyMood> = {
  "A*": "happy",
  A: "happy",
  B: "wink",
  C: "open",
  D: "thinking",
  E: "sad",
  F: "sad",
  G: "sad",
  U: "sad",
}

/** Saddest first, so a lower index is a sadder Binny. */
const SADDEST_FIRST: readonly BinnyMood[] = ["sad", "thinking", "open", "wink", "happy"]

const NEUTRAL: BinnyMood = "open"
const TOUGH_CEILING: BinnyMood = "thinking"

function rank(grade: string): number {
  return (LADDER as readonly string[]).indexOf(grade.trim())
}

/** The mood a grade alone gives; `null` for a grade off the ladder. */
export function moodForGrade(grade: string): BinnyMood | null {
  const i = rank(grade)
  return i === -1 ? null : MOOD_BY_GRADE[LADDER[i]!]
}

function sadder(a: BinnyMood, b: BinnyMood): BinnyMood {
  return SADDEST_FIRST.indexOf(a) <= SADDEST_FIRST.indexOf(b) ? a : b
}

function dropped(grade: string, previousGrade: string | null): boolean {
  if (previousGrade === null) return false
  const now = rank(grade)
  const before = rank(previousGrade)
  return now !== -1 && before !== -1 && now < before
}

/** The mood for a result or tough paper stage. */
export function paperMood(paper: { kind: "result" | "tough"; grade: string; previousGrade: string | null }): BinnyMood {
  const fromGrade = moodForGrade(paper.grade) ?? NEUTRAL
  const hard = paper.kind === "tough" || dropped(paper.grade, paper.previousGrade)
  return hard ? sadder(fromGrade, TOUGH_CEILING) : fromGrade
}
