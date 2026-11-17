// web/src/portals/student/screens/flashcards/reviewView.ts
import type { CardDTO, GenerationStatusDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { knewCount, xpEarned, type FlashcardSessionState } from "@/lib/flashcardSession"
import type { FcMood } from "./flashcardsView"

export const GRADE_ORDER: readonly ReviewGrade[] = ["again", "hard", "good", "easy"]
const GRADE_LABEL: Record<ReviewGrade, string> = { again: "Again", hard: "Hard", good: "Good", easy: "Easy" }

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`

export function intervalLabel(days: number, againDelayMinutes: number): string {
  if (days <= 0) return `${againDelayMinutes} min`
  if (days < 7) return plural(days, "day")
  if (days < 30) return plural(Math.floor(days / 7), "week")
  if (days < 365) return plural(Math.max(1, Math.round(days / 30)), "month")
  return plural(Math.round(days / 365), "year")
}

export interface GradeButtonView {
  grade: ReviewGrade
  label: string
  interval: string
  key: "1" | "2" | "3" | "4"
  tone: ReviewGrade
}

export function gradeButtons(card: CardDTO, againDelayMinutes: number): GradeButtonView[] {
  return GRADE_ORDER.map((grade, i) => ({
    grade,
    label: GRADE_LABEL[grade],
    interval: intervalLabel(card.nextIntervalDays[grade], againDelayMinutes),
    key: String(i + 1) as GradeButtonView["key"],
    tone: grade,
  }))
}

export type ReviewKeyAction = { kind: "reveal" } | { kind: "grade"; grade: ReviewGrade }

/** Space/Enter flip before the reveal; 1-4 rate after it. Anything else is ignored. */
export function reviewKeyAction(key: string, revealed: boolean): ReviewKeyAction | null {
  if (!revealed) return key === " " || key === "Enter" ? { kind: "reveal" } : null
  const i = ["1", "2", "3", "4"].indexOf(key)
  return i < 0 ? null : { kind: "grade", grade: GRADE_ORDER[i] }
}

export function progressView(index: number, total: number): { label: string; fraction: number } {
  const current = Math.min(index + 1, total)
  return { label: `${current}/${total}`, fraction: total ? current / total : 0 }
}

export function syncBannerText(failedCount: number): string | null {
  return failedCount > 0 ? `${plural(failedCount, "rating")} not saved yet` : null
}

export interface ComingBackRow {
  title: string
  sub: string | null
}

function dayIndex(d: Date, now: Date): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((a - b) / 86_400_000)
}

/** From the server forecast only. Later today first (the Again cards), then tomorrow, then the
 * biggest later day. At most two rows. */
export function comingBackRows(upcoming: readonly string[], now: Date): ComingBackRow[] {
  const byDay = new Map<number, number>()
  for (const iso of upcoming) {
    const d = dayIndex(new Date(iso), now)
    byDay.set(d, (byDay.get(d) ?? 0) + 1)
  }
  const rows: ComingBackRow[] = []
  const today = byDay.get(0) ?? 0
  if (today > 0) rows.push({ title: `${plural(today, "card")} later today`, sub: "The ones you marked Again" })
  const tomorrow = byDay.get(1) ?? 0
  if (tomorrow > 0) rows.push({ title: `${plural(tomorrow, "card")} tomorrow`, sub: null })
  const later = [...byDay.entries()].filter(([d]) => d >= 2).sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]
  if (later) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + later[0])
    rows.push({
      title: `Next big review ${date.toLocaleDateString(undefined, { weekday: "long" })}`,
      sub: plural(later[1], "card"),
    })
  }
  return rows.length ? rows.slice(0, 2) : [{ title: "Nothing due this week", sub: null }]
}

/** The done screen's "Today 2 of 3" ring needs L1's home data. Until L1 lands the screen
 * shows the two stats (knew it, XP) with no ring; flip this one flag to bring it back. */
export const SHOW_TODAY_RING = false

export interface DoneInput {
  session: FlashcardSessionState
  totalCards: number
  /** Due cards beyond this session's snapshot (`totalDue - totalCards`), or 0. */
  stillDue: number
  upcoming: readonly string[]
  now: Date
  practice: { subjectCode: string; topicName: string; marksLost: number } | null
}

export interface DoneView {
  mood: FcMood
  title: string
  sub: string
  knew: number
  xp: number
  stillDueLine: string | null
  savingLine: string | null
  comingBack: ComingBackRow[]
  practiceLink: { label: string; to: string } | null
}

export function doneView(input: DoneInput): DoneView {
  const { session } = input
  const knew = knewCount(session.results)
  const reviewed = session.results.length
  const combo = session.bestCombo >= 2 ? ` · best combo ×${session.bestCombo}` : ""
  return {
    mood: reviewed === 0 || knew / reviewed >= 0.6 ? "happy" : "open",
    title: "All caught up",
    sub: `${plural(input.totalCards, "card")}${combo}`,
    knew,
    xp: xpEarned(session.results),
    stillDueLine: input.stillDue > 0 ? `${input.stillDue} more still due` : null,
    savingLine: session.inFlight > 0 ? `${plural(session.inFlight, "rating")} still saving` : null,
    comingBack: comingBackRows(input.upcoming, input.now),
    practiceLink: input.practice
      ? {
          label: `Practise ${input.practice.topicName} · +${input.practice.marksLost} marks`,
          to: `/student/practice/${input.practice.subjectCode}`,
        }
      : null,
  }
}

/** The real count, never the requested one (P4.9 honesty rule 2). */
export function generationOutcome(status: GenerationStatusDTO): { text: string; shortfall: boolean } {
  const requested = status.requestedCount ?? status.generatedCount
  if (status.generatedCount < requested) {
    return { text: `${status.generatedCount} of ${requested} cards written`, shortfall: true }
  }
  return { text: `${plural(status.generatedCount, "card")} ready`, shortfall: false }
}
