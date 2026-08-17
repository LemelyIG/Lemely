import { describe, expect, it } from "vitest"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
import { subjectIdentifier } from "@/lib/subjectIdentifier"

describe("qualificationLevelLabel", () => {
  it("resolves a known raw value to its label", () => {
    expect(qualificationLevelLabel("o_level")).toBe("O-Level")
  })

  it("returns null for null/undefined/unknown", () => {
    expect(qualificationLevelLabel(null)).toBeNull()
    expect(qualificationLevelLabel(undefined)).toBeNull()
    expect(qualificationLevelLabel("not_a_level")).toBeNull()
  })
})

describe("subjectIdentifier", () => {
  it("composes name-primary with level and code in the secondary line", () => {
    expect(subjectIdentifier("Physics", "0625", "igcse")).toEqual({
      primary: "Physics",
      secondary: "IGCSE · 0625",
    })
  })

  it("omits the level segment when level is null", () => {
    expect(subjectIdentifier("Physics", "0625", null)).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("omits the level segment when level is omitted entirely", () => {
    expect(subjectIdentifier("Physics", "0625")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("falls back to the code alone for an unrecognised level string", () => {
    expect(subjectIdentifier("Physics", "0625", "not_a_level")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })
})
