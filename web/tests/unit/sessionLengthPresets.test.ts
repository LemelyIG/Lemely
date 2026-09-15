import { describe, expect, it } from "vitest"
import {
  SESSION_LENGTH_PRESETS,
  presetForWeeklyHours,
  presetToWeeklyHours,
} from "@/portals/student/screens/onboarding/onboardingData"

/*
 * C3b · Session-length preset chips on the weekly-hours question. The slider
 * stays the source of truth (S-02's stored value is `weeklyStudyHours`, a
 * number) — the chips are shortcuts onto it, so a chip shows pressed only on
 * an exact match and `presetForWeeklyHours` never rounds or picks "closest".
 */

describe("SESSION_LENGTH_PRESETS", () => {
  it("lists three presets in ascending order", () => {
    expect(SESSION_LENGTH_PRESETS.map((p) => p.id)).toEqual(["20m", "45m", "1h"])
    expect(SESSION_LENGTH_PRESETS.map((p) => p.weeklyHours)).toEqual([2, 5, 7])
  })
})

describe("presetToWeeklyHours", () => {
  it("maps each preset id to its weekly-hours value", () => {
    expect(presetToWeeklyHours("20m")).toBe(2)
    expect(presetToWeeklyHours("45m")).toBe(5)
    expect(presetToWeeklyHours("1h")).toBe(7)
  })
})

describe("presetForWeeklyHours", () => {
  it("matches a slider value equal to a preset", () => {
    expect(presetForWeeklyHours(5)).toBe("45m")
  })

  it("is null for a value between presets — no closest-match guessing", () => {
    expect(presetForWeeklyHours(6)).toBeNull()
  })

  it("is null when the slider is unset", () => {
    expect(presetForWeeklyHours(null)).toBeNull()
  })
})
