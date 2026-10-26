import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  EMPTY_PROFILE_VALUES,
  EVIDENCE_MAX_BYTES,
  EVIDENCE_MAX_FILES,
  FIELD_LIMITS,
  IDENTIFY_LINE,
  MODERATED_FIELDS,
  MAX_SUBJECTS,
  OUTCOMES_CAPTION,
  RE_REVIEW_LINE,
  REPLY_CHECKED_LINE,
  SEARCH_NOTICE,
  UNDER_REVIEW_LINE,
  DOCUMENTS_SEEN_DISCLOSURE,
  DOCUMENTS_SEEN_LABEL,
  EVIDENCE_BADGE_LINE,
  EVIDENCE_NO_ID_LINE,
  REPLY_MAX,
  evidenceFileError,
  formatListedSince,
  replyStateView,
  reviewTextNote,
  validateReply,
  valuesFromProfile,
  evidenceUploadStatusMessage,
  buildCreateBody,
  buildUpdateBody,
  changeNeedsReview,
  listingBanner,
  moderatedFieldsChanged,
  profileErrorField,
  profileMode,
  reReviewNotice,
  stepsFor,
  submitBlockers,
  toggleBody,
  validateProfile,
  validateStep,
  type ProfileFormValues,
} from "@/lib/tutoring/profileSteps"

/*
 * T-16 / T-15 / T-21 (SPEC §d, §a.2, §a.3): the profile editor's steps and rules.
 *
 * The expected side is read out of the SPEC (fixed copy, step names, column
 * sizes) and out of the repository module (the moderated field list), so no
 * assertion compares the code with a literal written from the same source.
 */

const REPO = join(import.meta.dirname, "..", "..", "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")
const PROFILE_REPO = readFileSync(join(REPO, "lemely", "db", "tutor_profile_repo.py"), "utf8")

function block(startMarker: string, endMarker: string): string {
  const start = SPEC.indexOf(startMarker)
  const end = SPEC.indexOf(endMarker, start)
  expect(start, startMarker).toBeGreaterThan(-1)
  expect(end, endMarker).toBeGreaterThan(start)
  return SPEC.slice(start, end)
}

const T15 = block("**T-15 ·", "**T-16 ·")
const T16 = block("**T-16 ·", "**T-17 ·")
const T21 = block("**T-21 ·", "### Parent (P)")
const S34 = block("**S-34 ·", "**S-35 ·")

const camel = (name: string) => name.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())

function pythonModeratedFields(): string[] {
  const match = /MODERATED_FIELDS: Final = \(([^)]*)\)/.exec(PROFILE_REPO)
  expect(match).not.toBeNull()
  return [...(match?.[1] ?? "").matchAll(/"([a-z_]+)"/g)].map((m) => camel(m[1]))
}

function varcharSize(table: string, column: string): number {
  const row = SPEC.split("\n").find((line) => line.startsWith(`| \`${column}\` | varchar(`) && SPEC.includes(table))
  const size = /varchar\((\d+)\)/.exec(row ?? "")?.[1]
  expect(size, column).toBeDefined()
  return Number(size)
}

const filled: ProfileFormValues = {
  publicFirstName: "Amira",
  publicLastInitial: "K",
  headline: "IGCSE Maths and Additional Maths, exam technique first",
  subjectCodes: ["0580", "0606"],
  offersVirtual: true,
  offersInPerson: false,
  offersOther: false,
  areaCode: "cairo",
  bio: "Ten years teaching.",
  qualificationNote: "BSc Mathematics",
  otherModeNote: "",
}

describe("fixed copy equals the SPEC (parsed)", () => {
  it("the search notice (row 17)", () => {
    const spec = /fixed copy, always shown above the C-14 toggle "Show my card in search engines", default on\): "([^"]+)"/.exec(
      T16,
    )?.[1]
    expect(spec).toBeDefined()
    expect(spec!.length).toBeGreaterThan(100)
    expect(SEARCH_NOTICE).toBe(spec)
  })

  it("the line about being identifiable (PP-4)", () => {
    const spec = /a line: "([^"]+)"/.exec(T16)?.[1]
    expect(spec).toBe("Your first name, initial, city and subjects can identify you to people who know you.")
    expect(IDENTIFY_LINE).toBe(spec)
  })

  it("the re-review line", () => {
    const spec = /shows "(Saving sends your profile back for review and hides it until approved\.)"/.exec(T16)?.[1]
    expect(spec).toBeDefined()
    expect(RE_REVIEW_LINE).toBe(spec)
  })

  it("the under-review line on T-15", () => {
    const spec = /Under review: "([^"]+)"/.exec(T15)?.[1]
    expect(spec).toBe("Lemely is reviewing your profile. You'll get a notification.")
    expect(UNDER_REVIEW_LINE).toBe(spec)
  })

  it("the reply moderation line on T-21", () => {
    const spec = /"(Replies are checked by Lemely before students see them\.)"/.exec(T21)?.[1]
    expect(spec).toBeDefined()
    expect(REPLY_CHECKED_LINE).toBe(spec)
  })

  it("the results caption under the preview, with both windows filled in", () => {
    const spec = /caption under both: "([^"]+)"/.exec(S34)?.[1]
    expect(spec).toBeDefined()
    expect(spec).toContain("{duringWindowDays}")
    const expected = spec!.replace("{duringWindowDays}", "60").replace("{beforeLookbackDays}", "90")
    expect(OUTCOMES_CAPTION(60, 90)).toBe(expected)
    expect(OUTCOMES_CAPTION(60, 90)).not.toContain("{")
  })
})

describe("the five steps", () => {
  it("are named and ordered as the SPEC names them, for a new or unsubmitted profile", () => {
    for (const state of [null, "draft", "rejected"] as const) {
      const steps = stepsFor(state)
      expect(steps.map((s) => s.id)).toEqual(["card", "about", "evidence", "availability", "submit"])
      steps.forEach((step, index) => {
        expect(step.number).toBe(index + 1)
        expect(T16, `${step.number} ${step.label}`).toContain(`${step.number} ${step.label}`)
      })
    }
  })

  it("has no Submit step once a profile is listed, and keeps it (as the review status) while one waits", () => {
    expect(stepsFor("listed").map((s) => s.id)).toEqual(["card", "about", "evidence", "availability"])
    expect(stepsFor("pending_review").map((s) => s.id)).toEqual(["card", "about", "evidence", "availability", "submit"])
  })

  it("is read-only when suspended or closed, and editable otherwise", () => {
    expect(profileMode(null)).toBe("onboarding")
    expect(profileMode("draft")).toBe("onboarding")
    expect(profileMode("rejected")).toBe("onboarding")
    expect(profileMode("pending_review")).toBe("edit")
    expect(profileMode("listed")).toBe("edit")
    expect(profileMode("suspended")).toBe("readonly")
    expect(profileMode("closed")).toBe("readonly")
  })
})

describe("the re-review line (moderated fields only)", () => {
  it("lists the moderated fields the repository lists", () => {
    const fromPython = pythonModeratedFields()
    expect(fromPython).toHaveLength(6)
    expect([...MODERATED_FIELDS].sort()).toEqual([...fromPython].sort())
  })

  it("shows when a listed profile changes any one moderated field", () => {
    // The other-way note only exists for a tutor who offers another way to meet.
    const base = { ...filled, offersOther: true, otherModeNote: "At the library" }
    for (const field of MODERATED_FIELDS) {
      const edited = { ...base, [field]: `${base[field]} changed` }
      expect(reReviewNotice("listed", base, edited), field).toBe(RE_REVIEW_LINE)
      expect(moderatedFieldsChanged(base, edited)).toEqual([field])
    }
  })

  it("does not show for a change to a field that is not moderated", () => {
    const edits: Partial<ProfileFormValues>[] = [
      { subjectCodes: ["0625"] },
      { offersVirtual: false, offersInPerson: true },
      { areaCode: "giza" },
    ]
    for (const edit of edits) {
      expect(reReviewNotice("listed", filled, { ...filled, ...edit })).toBeNull()
    }
  })

  it("does not show for whitespace-only differences, which the server ignores", () => {
    const edited = { ...filled, headline: `  ${filled.headline}  `, bio: `${filled.bio}\n` }
    expect(reReviewNotice("listed", filled, edited)).toBeNull()
    expect(moderatedFieldsChanged(filled, edited)).toEqual([])
  })

  it("does not show when nothing changed", () => {
    expect(reReviewNotice("listed", filled, { ...filled })).toBeNull()
  })

  it("shows only for a listed profile: other states are not sent back anywhere", () => {
    const edited = { ...filled, headline: "A different headline" }
    for (const state of [null, "draft", "pending_review", "rejected", "suspended", "closed"] as const) {
      expect(reReviewNotice(state, filled, edited), String(state)).toBeNull()
    }
  })

  it("never counts `indexable` or `paused` as a reason for review", () => {
    expect(changeNeedsReview("indexable")).toBe(false)
    expect(changeNeedsReview("paused")).toBe(false)
    for (const field of MODERATED_FIELDS) expect(changeNeedsReview(field)).toBe(true)
    expect(changeNeedsReview("subjectCodes")).toBe(false)
    expect(changeNeedsReview("areaCode")).toBe(false)
  })

  it("sends a toggle on its own, so it cannot carry a moderated edit", () => {
    expect(toggleBody("indexable", false)).toEqual({ indexable: false })
    expect(toggleBody("paused", true)).toEqual({ paused: true })
  })
})

describe("request bodies", () => {
  it("builds a create body from the form", () => {
    expect(buildCreateBody(filled)).toEqual({
      publicFirstName: "Amira",
      publicLastInitial: "K",
      headline: "IGCSE Maths and Additional Maths, exam technique first",
      bio: "Ten years teaching.",
      qualificationNote: "BSc Mathematics",
      subjectCodes: ["0580", "0606"],
      offersVirtual: true,
      offersInPerson: false,
      offersOther: false,
      otherModeNote: null,
      areaCode: "cairo",
    })
  })

  it("trims, and sends null for an empty initial or note", () => {
    const body = buildCreateBody({ ...filled, publicFirstName: "  Amira ", publicLastInitial: " ", qualificationNote: "  " })
    expect(body.publicFirstName).toBe("Amira")
    expect(body.publicLastInitial).toBeNull()
    expect(body.qualificationNote).toBeNull()
  })

  it("drops the other-way note unless the tutor offers another way (the database refuses it)", () => {
    expect(buildCreateBody({ ...filled, offersOther: false, otherModeNote: "At the library" }).otherModeNote).toBeNull()
    expect(buildCreateBody({ ...filled, offersOther: true, otherModeNote: " At the library " }).otherModeNote).toBe(
      "At the library",
    )
  })

  it("sends only what changed on an update", () => {
    expect(buildUpdateBody(filled, filled)).toEqual({})
    expect(buildUpdateBody(filled, { ...filled, headline: "New headline" })).toEqual({ headline: "New headline" })
    expect(buildUpdateBody(filled, { ...filled, subjectCodes: ["0625"], areaCode: "giza" })).toEqual({
      subjectCodes: ["0625"],
      areaCode: "giza",
    })
  })

  it("clears the other-way note when the way of meeting is switched off", () => {
    const saved = { ...filled, offersOther: true, otherModeNote: "At the library" }
    const body = buildUpdateBody(saved, { ...saved, offersOther: false })
    expect(body.offersOther).toBe(false)
    expect(body.otherModeNote).toBeNull()
  })

  it("never includes `paused` or `indexable` in a form update", () => {
    const body = buildUpdateBody(filled, { ...EMPTY_PROFILE_VALUES })
    expect(Object.keys(body)).not.toContain("paused")
    expect(Object.keys(body)).not.toContain("indexable")
  })
})

describe("validation", () => {
  it("takes its limits from the SPEC column sizes", () => {
    expect(FIELD_LIMITS.firstName).toBe(varcharSize("tutor_profiles", "public_first_name"))
    expect(FIELD_LIMITS.headline).toBe(varcharSize("tutor_profiles", "headline"))
    expect(FIELD_LIMITS.otherModeNote).toBe(varcharSize("tutor_profiles", "other_mode_note"))
    expect(FIELD_LIMITS.bio).toBe(Number(/`char_length\(bio\) <= (\d+)`/.exec(SPEC)?.[1]))
    expect(FIELD_LIMITS.qualificationNote).toBe(
      Number(/`char_length\(qualification_note\) <= (\d+)`/.exec(SPEC)?.[1]),
    )
    expect(MAX_SUBJECTS).toBe(Number(/Max (\d+) per tutor \(service\)\./.exec(SPEC)?.[1]))
    expect(EVIDENCE_MAX_FILES).toBe(Number(/Max (\d+) per tutor\. Images/.exec(SPEC)?.[1]))
    expect(EVIDENCE_MAX_BYTES).toBe(Number(/size_bytes_range`: `BETWEEN 1 AND (\d+)`/.exec(SPEC)?.[1]))
  })

  it("accepts a filled profile", () => {
    expect(validateProfile(filled)).toEqual({})
  })

  it("asks for a first name, a headline, a subject, a way to meet and an area", () => {
    const errors = validateStep("card", EMPTY_PROFILE_VALUES)
    expect(Object.keys(errors).sort()).toEqual(
      ["areaCode", "headline", "modes", "publicFirstName", "subjectCodes"].sort(),
    )
    for (const message of Object.values(errors)) expect(message.length).toBeGreaterThan(8)
  })

  it("holds a first name to letters, spaces, hyphens and apostrophes, 40 at most", () => {
    expect(validateStep("card", { ...filled, publicFirstName: "Amira2" }).publicFirstName).toBeDefined()
    expect(validateStep("card", { ...filled, publicFirstName: "amira@x" }).publicFirstName).toBeDefined()
    expect(validateStep("card", { ...filled, publicFirstName: "a".repeat(41) }).publicFirstName).toBeDefined()
    expect(validateStep("card", { ...filled, publicFirstName: "Mary-Anne" }).publicFirstName).toBeUndefined()
    expect(validateStep("card", { ...filled, publicFirstName: "O'Neil" }).publicFirstName).toBeUndefined()
    expect(validateStep("card", { ...filled, publicFirstName: "أميرة" }).publicFirstName).toBeUndefined()
  })

  it("holds the last initial to one letter", () => {
    expect(validateStep("card", { ...filled, publicLastInitial: "KH" }).publicLastInitial).toBeDefined()
    expect(validateStep("card", { ...filled, publicLastInitial: "7" }).publicLastInitial).toBeDefined()
    expect(validateStep("card", { ...filled, publicLastInitial: "" }).publicLastInitial).toBeUndefined()
  })

  it("holds the headline to its length and refuses more than ten subjects", () => {
    expect(validateStep("card", { ...filled, headline: "x".repeat(FIELD_LIMITS.headline + 1) }).headline).toBeDefined()
    const many = Array.from({ length: MAX_SUBJECTS + 1 }, (_, i) => `s${i}`)
    expect(validateStep("card", { ...filled, subjectCodes: many }).subjectCodes).toBeDefined()
  })

  it("holds the About step to its lengths", () => {
    expect(validateStep("about", { ...filled, bio: "x".repeat(FIELD_LIMITS.bio + 1) }).bio).toBeDefined()
    expect(
      validateStep("about", { ...filled, qualificationNote: "x".repeat(FIELD_LIMITS.qualificationNote + 1) })
        .qualificationNote,
    ).toBeDefined()
    expect(
      validateStep("about", { ...filled, offersOther: true, otherModeNote: "x".repeat(FIELD_LIMITS.otherModeNote + 1) })
        .otherModeNote,
    ).toBeDefined()
    expect(validateStep("about", filled)).toEqual({})
  })

  it("maps a server refusal to the field it is about", () => {
    expect(profileErrorField("invalid_public_name")).toBe("publicFirstName")
    expect(profileErrorField("invalid_subjects")).toBe("subjectCodes")
    expect(profileErrorField("invalid_modes")).toBe("modes")
    expect(profileErrorField("invalid_area")).toBe("areaCode")
    expect(profileErrorField("contact_details_not_allowed")).toBeNull()
    expect(profileErrorField("not_a_code")).toBeNull()
  })
})

describe("what blocks a submit", () => {
  const complete = {
    headline: "A headline",
    subjects: [{ code: "0580", name: "Mathematics" }],
    modes: ["virtual"] as ("virtual" | "in_person" | "other")[],
    areaCode: "cairo",
    availabilityCount: 3,
  }

  it("lists nothing for a complete profile", () => {
    expect(submitBlockers(complete)).toEqual([])
  })

  it("lists each missing part in words, availability included (SPEC §a.3 draft to pending_review)", () => {
    const blockers = submitBlockers({ headline: "", subjects: [], modes: [], areaCode: "", availabilityCount: 0 })
    expect(blockers.map((b) => b.step)).toEqual(["card", "card", "card", "card", "availability"])
    expect(blockers.at(-1)?.text).toContain("time")
    expect(submitBlockers({ ...complete, availabilityCount: 0 })).toHaveLength(1)
  })
})

describe("the listing banner on T-15", () => {
  it("says what each state means, in the SPEC's words where it has them", () => {
    expect(listingBanner("pending_review", { paused: false, reviewNote: null }).body).toBe(UNDER_REVIEW_LINE)
    expect(listingBanner(null, { paused: false, reviewNote: null }).title.length).toBeGreaterThan(5)
  })

  it("shows the reviewer's note for a rejection and for a suspension, and invents none", () => {
    expect(listingBanner("rejected", { paused: false, reviewNote: "Add your subjects." }).body).toContain("Add your subjects.")
    expect(listingBanner("suspended", { paused: false, reviewNote: "Please contact support." }).body).toContain(
      "Please contact support.",
    )
    expect(listingBanner("rejected", { paused: false, reviewNote: null }).body).not.toContain("null")
    expect(listingBanner("suspended", { paused: false, reviewNote: null }).body.length).toBeGreaterThan(10)
  })

  it("tells a paused listing apart from a live one", () => {
    const live = listingBanner("listed", { paused: false, reviewNote: null })
    const paused = listingBanner("listed", { paused: true, reviewNote: null })
    expect(paused.title).not.toBe(live.title)
    expect(paused.tone).not.toBe("ok")
  })

  it("never says verified or improvement", () => {
    for (const state of [null, "draft", "pending_review", "listed", "rejected", "suspended", "closed"] as const) {
      const banner = listingBanner(state, { paused: false, reviewNote: null })
      expect(`${banner.title} ${banner.body}`).not.toMatch(/\b(verified|improvements?)\b/i)
    }
  })
})

describe("more fixed copy, parsed from the SPEC", () => {
  it("the two evidence lines on step 3", () => {
    expect(/"(Don't upload identity documents\.)"/.exec(T16)?.[1]).toBe(EVIDENCE_NO_ID_LINE)
    expect(/"(Changing your documents removes the 'Documents seen' badge until Lemely looks again\.)"/.exec(T16)?.[1]).toBe(
      EVIDENCE_BADGE_LINE,
    )
  })

  it("the documents-seen label and disclosure of the preview", () => {
    expect(/"(Documents seen by Lemely)" when `documentsSeen`/.exec(S34)?.[1]).toBe(DOCUMENTS_SEEN_LABEL)
    expect(/disclosure: "([^"]+)"/.exec(S34)?.[1]).toBe(DOCUMENTS_SEEN_DISCLOSURE)
  })

  it("the reply limit equals the reply table's check", () => {
    const table = SPEC.slice(SPEC.indexOf("#### `tutor_review_replies`"))
    expect(Number(/btrim\(body\)\) BETWEEN 1 AND (\d+)/.exec(table)?.[1])).toBe(REPLY_MAX)
  })
})

describe("reading a profile back into the form", () => {
  const base = {
    headline: "Maths",
    subjects: [{ code: "0580", name: "Mathematics" }],
    modes: ["virtual", "other"] as ("virtual" | "in_person" | "other")[],
    area: { code: "cairo", name: "Cairo" },
    bio: "Bio",
    qualificationNote: null,
    otherModeNote: "At a cafe",
  }

  it("splits the public name back into first name and initial", () => {
    expect(valuesFromProfile({ ...base, publicName: "Amira K." })).toMatchObject({
      publicFirstName: "Amira",
      publicLastInitial: "K",
    })
    expect(valuesFromProfile({ ...base, publicName: "Mary Anne R." })).toMatchObject({
      publicFirstName: "Mary Anne",
      publicLastInitial: "R",
    })
    expect(valuesFromProfile({ ...base, publicName: "Amira" })).toMatchObject({
      publicFirstName: "Amira",
      publicLastInitial: "",
    })
  })

  it("reads modes, subjects, area and notes", () => {
    const values = valuesFromProfile({ ...base, publicName: "Amira K." })
    expect(values).toMatchObject({
      subjectCodes: ["0580"],
      offersVirtual: true,
      offersInPerson: false,
      offersOther: true,
      areaCode: "cairo",
      qualificationNote: "",
      otherModeNote: "At a cafe",
    })
  })

  it("a profile read back and saved unchanged sends nothing", () => {
    const values = valuesFromProfile({ ...base, publicName: "Amira K." })
    expect(buildUpdateBody(values, { ...values })).toEqual({})
  })
})

describe("evidence and replies", () => {
  it("stops at five files and at 10 MB", () => {
    const five = Array.from({ length: EVIDENCE_MAX_FILES }, (_, i) => ({ evidenceId: String(i) })) as never[]
    expect(evidenceFileError({ size: 1000 }, five)).not.toBeNull()
    expect(evidenceFileError({ size: 1000 }, five.slice(0, 4))).toBeNull()
    expect(evidenceFileError({ size: EVIDENCE_MAX_BYTES }, [])).toBeNull()
    expect(evidenceFileError({ size: EVIDENCE_MAX_BYTES + 1 }, [])).not.toBeNull()
    expect(evidenceFileError({ size: 0 }, [])).not.toBeNull()
  })

  it("will not send a blank or over-long reply", () => {
    expect(validateReply("  \n ")).not.toBeNull()
    expect(validateReply("Thank you.")).toBeNull()
    expect(validateReply("x".repeat(REPLY_MAX))).toBeNull()
    expect(validateReply("x".repeat(REPLY_MAX + 1))).not.toBeNull()
  })

  it("names each moderation state of a reply in words, all different", () => {
    const labels = (["pending", "approved", "rejected"] as const).map((s) => replyStateView(s).label)
    expect(new Set(labels).size).toBe(3)
    expect(replyStateView("rejected").tone).toBe("warn")
  })

  it("explains a review whose words are not shown, and says nothing otherwise", () => {
    expect(reviewTextNote("pending")).not.toBeNull()
    expect(reviewTextNote("rejected")).not.toBeNull()
    expect(reviewTextNote("approved")).toBeNull()
    expect(reviewTextNote("none")).toBeNull()
  })

  it("writes the listed-since month, and nothing for a profile never listed", () => {
    expect(formatListedSince("2026-07")).toBe("Jul 2026")
    expect(formatListedSince("2026-13")).toBeNull()
    expect(formatListedSince(null)).toBeNull()
  })
})

describe("evidence upload failures", () => {
  it("words the three statuses T6 sends without a code, and leaves the rest to the caller", () => {
    expect(evidenceUploadStatusMessage(new ApiError(413, "x", null))).toContain("10 MB")
    expect(evidenceUploadStatusMessage(new ApiError(415, "x", null))).toContain("PDF")
    expect(evidenceUploadStatusMessage(new ApiError(503, "x", null))).toContain("Try again")
    expect(evidenceUploadStatusMessage(new ApiError(409, "x", { code: "evidence_limit" }))).toBeNull()
    expect(evidenceUploadStatusMessage(new Error("network"))).toBeNull()
  })
})

describe("the last initial is shown in upper case, so it is compared and sent that way", () => {
  it("does not send a profile back to review because the tutor typed a lower-case initial", () => {
    const saved = { ...filled, publicLastInitial: "K" }
    const edited = { ...filled, publicLastInitial: "k" }
    expect(moderatedFieldsChanged(saved, edited)).toEqual([])
    expect(reReviewNotice("listed", saved, edited)).toBeNull()
    expect(buildUpdateBody(saved, edited)).toEqual({})
  })

  it("sends it in upper case", () => {
    expect(buildCreateBody({ ...filled, publicLastInitial: "k" }).publicLastInitial).toBe("K")
    expect(buildUpdateBody({ ...filled, publicLastInitial: "K" }, { ...filled, publicLastInitial: "m" })).toEqual({
      publicLastInitial: "M",
    })
  })
})
