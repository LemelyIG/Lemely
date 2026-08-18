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

  it("drops the code from secondary when the name has resolved to the code itself", () => {
    // An unregistered subject code — `get_profile(code).name or code` falls
    // back to the code, so `name === code` and printing the code again would
    // stack the same string on top of itself.
    expect(subjectIdentifier("0620", "0620", null)).toEqual({
      primary: "0620",
      secondary: "",
    })
  })

  it("still shows the level when name has resolved to the code itself", () => {
    expect(subjectIdentifier("0620", "0620", "igcse")).toEqual({
      primary: "0620",
      secondary: "IGCSE",
    })
  })
})
