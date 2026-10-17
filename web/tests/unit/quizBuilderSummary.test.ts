import { describe, expect, it } from "vitest"
import {
  QUIZ_MINUTES_PER_QUESTION,
  estimateQuizMinutes,
  quizLengthUpperBound,
  settingsSoFar,
} from "@/lib/quizBuilderSummary"
import type { QuizDetail } from "@/lib/teacherTypes"

/*
 * Task 8 (C3c) · QuizBuilder's "So far" rail. `settingsSoFar` reads five
 * fixed labels (Title, Subject, Questions, Difficulty, Pool) each anchored
 * to the step that sets it (1, 1, 4, 3, 4) and includes a label only once
 * the builder is strictly past that step *and* the field actually has a
 * value — a rail that showed a step's own in-progress value would blur the
 * line between "decided" and "being decided".
 */

const FIXTURE: QuizDetail = {
  quiz: {
    id: "quiz-1",
    subjectCode: "0625",
    title: "Mock exam warm-up",
    status: "draft",
    targetGrade: "B",
    includedTopics: [],
    poolSource: "past_paper",
    requestedCount: 10,
    timeLimitMinutes: null,
    builderStep: 1,
    questionCount: 0,
  },
  questions: [],
}

describe("settingsSoFar", () => {
  it("is empty at step 1 — nothing is 'so far' yet", () => {
    expect(settingsSoFar(FIXTURE, 1)).toEqual([])
  })

  it("at step 3 shows only what step 1 (Basics) already set", () => {
    expect(settingsSoFar(FIXTURE, 3)).toEqual([
      { label: "Title", value: "Mock exam warm-up" },
      { label: "Subject", value: "0625" },
    ])
  })

  it("at step 6 shows every completed step's value", () => {
    expect(settingsSoFar(FIXTURE, 6)).toEqual([
      { label: "Title", value: "Mock exam warm-up" },
      { label: "Subject", value: "0625" },
      { label: "Questions", value: "10 questions" },
      { label: "Difficulty", value: "B" },
      { label: "Pool", value: "Past papers" },
    ])
  })

  it("omits a field with no value even once its step is behind", () => {
    const noDifficulty: QuizDetail = {
      ...FIXTURE,
      quiz: { ...FIXTURE.quiz, targetGrade: null, poolSource: null, requestedCount: null },
    }
    expect(settingsSoFar(noDifficulty, 6)).toEqual([
      { label: "Title", value: "Mock exam warm-up" },
      { label: "Subject", value: "0625" },
    ])
  })
})

describe("QUIZ_MINUTES_PER_QUESTION / estimateQuizMinutes", () => {
  it("is 2.5 minutes per question, rounded up", () => {
    expect(QUIZ_MINUTES_PER_QUESTION).toBe(2.5)
    expect(estimateQuizMinutes(7)).toBe(18)
  })

  it("rounds an exact half-minute total down to itself, not up", () => {
    expect(estimateQuizMinutes(4)).toBe(10)
  })
})

describe("quizLengthUpperBound", () => {
  it("defaults to 50 when the pool count is unknown", () => {
    expect(quizLengthUpperBound(null)).toBe(50)
  })

  it("uses the pool count when known", () => {
    expect(quizLengthUpperBound(12)).toBe(12)
  })

  it("clamps a zero pool count up to a minimum of 1 — a slider cannot have a 0 max", () => {
    expect(quizLengthUpperBound(0)).toBe(1)
  })

  it("clamps a pool count above 50 down to 50", () => {
    expect(quizLengthUpperBound(400)).toBe(50)
  })
})
