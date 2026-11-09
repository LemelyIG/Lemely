import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * The admin detail DTO (`WaitlistApplicantDTO`, camelCase) and the detail sheet must agree, and the
 * sheet must show every field. The list below is the backend's final field set; there is no referrer.
 */
const FIELDS = [
  "id", "email", "name", "role", "centreName", "levels", "subjects", "otherSubjects", "examBoards",
  "examSession", "phone", "phoneHasWhatsapp", "emailConfirmed", "consentVersion", "consentText",
  "consentAt", "status", "adminNote", "utmSource", "utmMedium", "utmCampaign", "utmContent", "utmTerm",
  "completedAt", "partial", "createdAt", "updatedAt",
] as const

const ROOT = join(import.meta.dirname, "..", "..")
const api = readFileSync(join(ROOT, "src/lib/waitlist-api.ts"), "utf8")
const sheet = readFileSync(join(ROOT, "src/portals/admin/screens/Waitlist.tsx"), "utf8")

describe("WaitlistApplicant matches the backend's admin detail DTO", () => {
  const body = api.slice(api.indexOf("export interface WaitlistApplicant {"))
  const iface = body.slice(0, body.indexOf("\n}"))
  const declared = [...iface.matchAll(/^\s{2}(\w+)\??:/gm)].map((m) => m[1])

  it("declares exactly those fields", () => {
    expect([...declared].sort()).toEqual([...FIELDS].sort())
  })

  it("has no referrer", () => {
    expect(declared).not.toContain("referrer")
  })
})

describe("the applicant sheet shows every field", () => {
  const start = sheet.indexOf("function ApplicantSheet")
  const sheetSource = sheet.slice(start) + sheet.slice(sheet.indexOf("function NoteField"), sheet.indexOf("export function WaitlistQueueView"))
  it.each(FIELDS)("%s", (field) => {
    expect(sheetSource).toMatch(new RegExp(`\\b(current|applicant)\\.${field}\\b`))
  })
})
