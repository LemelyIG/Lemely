/*
 * Binny's mood for a marked paper. Pure: the grade alone decides it. Owner decision 2026-11-24: the lower the grade,
 * the sadder Binny gets, encouraging and never shaming. Only the poses the Binny component already draws are used
 * (happy, wink, open, thinking, sad); nothing here asks for new art. Motion stays with `motionFor` in model.ts: only
 * a happy Binny hops.
 *
 *   A*, A  happy      B  wink      C  open      D  thinking      E, F, G, U  sad
 *
 * The previous grade and the server's "tough" flag do not move the mood: "From A* to A" is still an A. A grade off
 * this ladder makes no claim: `open`.
 */
import type { BinnyMood } from "@/components/redesign"

const MOOD_BY_GRADE: ReadonlyMap<string, BinnyMood> = new Map<string, BinnyMood>([
  ["A*", "happy"],
  ["A", "happy"],
  ["B", "wink"],
  ["C", "open"],
  ["D", "thinking"],
  ["E", "sad"],
  ["F", "sad"],
  ["G", "sad"],
  ["U", "sad"],
])

const NEUTRAL: BinnyMood = "open"

/** The mood for a result or tough paper stage: a function of its grade, nothing else. */
export function paperMood(paper: { grade: string }): BinnyMood {
  return MOOD_BY_GRADE.get(paper.grade.trim()) ?? NEUTRAL
}
