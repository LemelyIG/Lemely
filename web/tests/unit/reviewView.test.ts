import { describe, expect, it } from "vitest"
import {
  SHORT_ANSWER_CHARS,
  answerSize,
  comingBackRows,
  doneView,
  generationOutcome,
  gradeButtons,
  intervalLabel,
  progressView,
  reviewKeyAction,
  syncBannerText,
} from "@/portals/student/screens/flashcards/reviewView"
import { startSession } from "@/lib/flashcardSession"
import type { CardDTO, ReviewResultDTO } from "@/lib/flashcardTypes"

const NOW = new Date("2026-11-16T09:00:00") // a Monday

const card: CardDTO = {
  id: "c1", front: "f", back: "b", position: 1, source: "manual", sourceQuestionId: null,
  repetitions: 2, easeFactor: 2.5, intervalDays: 6, lapses: 0, dueAt: "2026-11-16T08:00:00Z",
  lastReviewedAt: null, nextIntervalDays: { again: 0, hard: 1, good: 15, easy: 40 },
}

function res(grade: ReviewResultDTO["grade"], xp = 1): ReviewResultDTO {
  return { card, reviewId: "r", grade, intervalBeforeDays: 6, intervalAfterDays: 15, xpAwarded: xp }
}

describe("intervals and grade buttons", () => {
  it("speaks intervals in plain units", () => {
    expect(intervalLabel(0, 10)).toBe("10 min")
    expect(intervalLabel(1, 10)).toBe("1 day")
    expect(intervalLabel(3, 10)).toBe("3 days")
    expect(intervalLabel(7, 10)).toBe("1 week")
    expect(intervalLabel(15, 10)).toBe("2 weeks")
    expect(intervalLabel(40, 10)).toBe("1 month")
    expect(intervalLabel(400, 10)).toBe("1 year")
    // "10 min" belongs to Again alone; any other grade is at least a day, and fractions round.
    expect(intervalLabel(0, 10, "hard")).toBe("1 day")
    expect(intervalLabel(0, 10, "again")).toBe("10 min")
    expect(intervalLabel(2.6, 10, "good")).toBe("3 days")
    expect(intervalLabel(0.4, 10, "easy")).toBe("1 day")
  })

  it("lists Again, Hard, Good, Easy with keys 1-4 and real intervals", () => {
    expect(gradeButtons(card, 10)).toEqual([
      { grade: "again", label: "Again", interval: "10 min", key: "1", tone: "again" },
      { grade: "hard", label: "Hard", interval: "1 day", key: "2", tone: "hard" },
      { grade: "good", label: "Good", interval: "2 weeks", key: "3", tone: "good" },
      { grade: "easy", label: "Easy", interval: "1 month", key: "4", tone: "easy" },
    ])
  })
})

describe("reviewKeyAction", () => {
  it("flips on Space or Enter before the reveal, and ignores digits then", () => {
    expect(reviewKeyAction(" ", false)).toEqual({ kind: "reveal" })
    expect(reviewKeyAction("Enter", false)).toEqual({ kind: "reveal" })
    expect(reviewKeyAction("3", false)).toBeNull()
  })
  it("rates 1-4 after the reveal and ignores Space then", () => {
    expect(reviewKeyAction("1", true)).toEqual({ kind: "grade", grade: "again" })
    expect(reviewKeyAction("4", true)).toEqual({ kind: "grade", grade: "easy" })
    expect(reviewKeyAction(" ", true)).toBeNull()
    expect(reviewKeyAction("5", true)).toBeNull()
  })
})

describe("progress and the sync banner", () => {
  it("shows the card on screen out of the total, clamped", () => {
    expect(progressView(3, 26)).toEqual({ label: "4/26", fraction: 4 / 26 })
    expect(progressView(30, 26)).toEqual({ label: "26/26", fraction: 1 })
  })
  it("names unsaved ratings, or nothing", () => {
    expect(syncBannerText(0)).toBeNull()
    expect(syncBannerText(1)).toBe("1 rating not saved yet")
    expect(syncBannerText(3)).toBe("3 ratings not saved yet")
  })
})

describe("comingBackRows", () => {
  it("lists later today, tomorrow and the biggest later day, at most two rows", () => {
    const upcoming = [
      "2026-11-16T09:10:00",
      "2026-11-17T08:00:00", "2026-11-17T09:00:00",
      "2026-11-19T08:00:00",
      "2026-11-21T08:00:00", "2026-11-21T09:00:00", "2026-11-21T10:00:00",
    ]
    expect(comingBackRows(upcoming, NOW, 1)).toEqual([
      { title: "1 card later today", sub: "The ones you marked Again" },
      { title: "2 cards tomorrow", sub: null },
    ])
    // No Again this session: the sub would be untrue, so it is dropped.
    expect(comingBackRows(upcoming, NOW)[0]).toEqual({ title: "1 card later today", sub: null })
    expect(comingBackRows(upcoming.slice(1), NOW)).toEqual([
      { title: "2 cards tomorrow", sub: null },
      { title: "Next big review Saturday", sub: "3 cards" },
    ])
    expect(comingBackRows([], NOW)).toEqual([{ title: "Nothing due this week", sub: null }])
  })
})

describe("doneView", () => {
  it("celebrates with knew-it, XP, best combo and a practice link", () => {
    const session = {
      ...startSession(),
      results: [res("good", 2), res("easy", 2), res("again", 0)],
      bestCombo: 2,
    }
    expect(
      doneView({
        session, totalCards: 3, stillDue: 0, upcoming: [], now: NOW,
        practice: { subjectCode: "0580", topicName: "Vectors", marksLost: 9 },
      }),
    ).toEqual({
      mood: "happy",
      title: "All caught up",
      sub: "3 cards · best combo ×2",
      knew: 2,
      xp: 4,
      stillDueLine: null,
      savingLine: null,
      comingBack: [{ title: "Nothing due this week", sub: null }],
      practiceLink: { label: "Practise Vectors · cost you 9 marks", to: "/student/practice/0580" },
    })
  })

  it("says “1 mark” in the singular in the practice link", () => {
    const view = doneView({
      session: { ...startSession(), results: [res("good", 1)] }, totalCards: 1, stillDue: 0, upcoming: [], now: NOW,
      practice: { subjectCode: "0580", topicName: "Vectors", marksLost: 1 },
    })
    expect(view.practiceLink?.label).toBe("Practise Vectors · cost you 1 mark")
  })

  it("drops the combo under 2, softens Binny on a rough run, and names unfinished work", () => {
    const session = { ...startSession(), results: [res("again", 0), res("again", 0), res("good", 1)], inFlight: 2 }
    const view = doneView({ session, totalCards: 3, stillDue: 4, upcoming: [], now: NOW, practice: null })
    expect(view.sub).toBe("3 cards")
    expect(view.mood).toBe("open")
    expect(view.stillDueLine).toBe("4 more still due")
    expect(view.savingLine).toBe("2 ratings still saving")
    expect(view.practiceLink).toBeNull()
  })
})

describe("generationOutcome", () => {
  it("reports the real count and names a shortfall", () => {
    const base = { deckId: "d", status: "ready" as const, error: null }
    expect(generationOutcome({ ...base, requestedCount: 12, generatedCount: 12 })).toEqual({
      text: "12 cards ready", shortfall: false,
    })
    expect(generationOutcome({ ...base, requestedCount: 12, generatedCount: 9 })).toEqual({
      text: "9 of 12 cards written", shortfall: true,
    })
  })
})

describe("answerSize", () => {
  it("keeps the mock's 34px for an answer that fits a phone line", () => {
    expect(answerSize("½(a + b)")).toBe("text-[34px]")
    expect(answerSize("x".repeat(SHORT_ANSWER_CHARS))).toBe("text-[34px]")
  })

  it("steps a longer answer down with the viewport so it wraps instead of overflowing", () => {
    expect(answerSize("x".repeat(SHORT_ANSWER_CHARS + 1))).toBe("text-[clamp(18px,6vw,34px)]")
    expect(answerSize("The midpoint of AB is half of a plus b")).toBe("text-[clamp(18px,6vw,34px)]")
  })

  it("measures the trimmed answer, so padding spaces never tip a short answer into the clamp", () => {
    expect(answerSize(`  ${"x".repeat(SHORT_ANSWER_CHARS)}  `)).toBe("text-[34px]")
  })
})
