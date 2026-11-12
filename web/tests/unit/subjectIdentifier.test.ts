import { describe, expect, it } from "vitest"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import type { LabelledValue } from "@/lib/referenceTypes"

// The table `/api/reference` serves in production (mirrors
// `lemely.db.models.enums.QualificationLevel`). A local fixture, not a
// frontend constant: the whole point of this task is that the frontend no
// longer owns a copy of this table.
const LEVELS: LabelledValue[] = [
  { value: "igcse", label: "IGCSE" },
  { value: "o_level", label: "O-Level" },
  { value: "as_level", label: "AS-Level" },
  { value: "a_level", label: "A-Level" },
]

describe("qualificationLevelLabel", () => {
  it("resolves a known raw value to its label", () => {
    expect(qualificationLevelLabel(LEVELS, "o_level")).toBe("O-Level")
  })

  it("returns null for null/undefined/unknown", () => {
    expect(qualificationLevelLabel(LEVELS, null)).toBeNull()
    expect(qualificationLevelLabel(LEVELS, undefined)).toBeNull()
    expect(qualificationLevelLabel(LEVELS, "not_a_level")).toBeNull()
  })

  it("returns null while the table is still loading", () => {
    expect(qualificationLevelLabel(undefined, "igcse")).toBeNull()
  })
})

describe("subjectIdentifier", () => {
  it("composes name-primary with level and code in the secondary line", () => {
    expect(subjectIdentifier(LEVELS, "Physics", "0625", "igcse")).toEqual({
      primary: "Physics",
      secondary: "IGCSE · 0625",
    })
  })

  it("omits the level segment when level is null", () => {
    expect(subjectIdentifier(LEVELS, "Physics", "0625", null)).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("omits the level segment when level is omitted entirely", () => {
    expect(subjectIdentifier(LEVELS, "Physics", "0625")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("falls back to the code alone for an unrecognised level string", () => {
    expect(subjectIdentifier(LEVELS, "Physics", "0625", "not_a_level")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("drops the code from secondary when the name has resolved to the code itself", () => {
    // An unregistered subject code — `get_profile(code).name or code` falls
    // back to the code, so `name === code` and printing the code again would
    // stack the same string on top of itself.
    expect(subjectIdentifier(LEVELS, "0620", "0620", null)).toEqual({
      primary: "0620",
      secondary: "",
    })
  })

  it("still shows the level when name has resolved to the code itself", () => {
    expect(subjectIdentifier(LEVELS, "0620", "0620", "igcse")).toEqual({
      primary: "0620",
      secondary: "IGCSE",
    })
  })

  it("omits the level segment while the table is still loading", () => {
    expect(subjectIdentifier(undefined, "Physics", "0625", "igcse")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })
})
