import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { stripComments } from "./support/jsxSource"
import {
  CONTACT_DETAILS_MESSAGE,
  NOTES_FIXED_LINE,
  NOTES_FROZEN_LINE,
  NOTES_CONTACT_DETAILS_MESSAGE,
  NOTES_HIDDEN_PLACEHOLDER,
  NOTES_TUTOR_PARENTS_LINE,
  REPORT_DETAILS_MAX,
  REPORT_REASONS,
  DOCUMENTS_SEEN_SENTENCE,
  SAFETY_NOTICE_BUTTON,
  SAFETY_NOTICE_NOT_NOW,
  SAFETY_NOTICE_PARAGRAPHS,
  SAFETY_NOTICE_TITLE,
  blockCopy,
  safetyNoticeParagraphs,
  notesComposerState,
  reportReasonsFor,
  reportShowsHelpline,
  safetyActionError,
  sendNoteDraft,
} from "@/lib/tutoring/safetyNoticeCopy"

/*
 * C-24 (SPEC §d): the first-booking safety notice. The copy is FIXED by the SPEC
 * and the expected side is parsed out of the SPEC text, so this test cannot
 * agree with a stale copy of it. The same goes for the fixed lines of C-21 and
 * the report reasons (SPEC §a.1 `reportreason`).
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

function specNotice(): { title: string; paragraphs: string[]; button: string } {
  const start = SPEC.indexOf("**C-24 copy (fixed).**")
  expect(start).toBeGreaterThan(-1)
  const end = SPEC.indexOf("Shown once per student", start)
  expect(end).toBeGreaterThan(start)
  const block = SPEC.slice(start, end)
  const title = /Title: "([^"]+)"/.exec(block)?.[1] ?? ""
  const button = /Button: "([^"]+)"/.exec(block)?.[1] ?? ""
  const paragraphs = block
    .split("\n")
    .filter((line) => line.startsWith('- "'))
    .map((line) => line.slice(3, line.lastIndexOf('"')))
  return { title, paragraphs, button }
}

const notice = specNotice()

describe("C-24 safety notice copy", () => {
  it("parses five paragraphs, a title and a button out of the SPEC", () => {
    expect(notice.paragraphs).toHaveLength(5)
    expect(notice.title).toBe("Before your first session")
    expect(notice.button).toBe("I understand")
  })

  it("equals the SPEC verbatim, paragraph by paragraph", () => {
    expect(SAFETY_NOTICE_TITLE).toBe(notice.title)
    expect([...SAFETY_NOTICE_PARAGRAPHS]).toEqual(notice.paragraphs)
    expect(SAFETY_NOTICE_BUTTON).toBe(notice.button)
  })

  /*
   * "Lemely looked at documents they uploaded" is true only for a tutor an admin has
   * looked at documents for (`documentsSeen`). The SPEC stays the source of the base
   * text; the one sentence is conditional, so it is tested on its own.
   */
  it("shows the SPEC's five paragraphs unchanged when the tutor's documents were seen", () => {
    expect([...safetyNoticeParagraphs(true)]).toEqual(notice.paragraphs)
  })

  it("takes the documents sentence from the SPEC's first paragraph and nowhere else", () => {
    expect(notice.paragraphs[0]).toContain(DOCUMENTS_SEEN_SENTENCE)
    expect(DOCUMENTS_SEEN_SENTENCE).toBe("Lemely looked at documents they uploaded.")
    expect(notice.paragraphs.slice(1).filter((p) => p.includes(DOCUMENTS_SEEN_SENTENCE))).toEqual([])
  })

  it("drops only that sentence, and leaves the other four paragraphs verbatim, when documents were not seen", () => {
    const without = safetyNoticeParagraphs(false)
    expect(without).toHaveLength(5)
    expect(without[0]).toBe(notice.paragraphs[0].replace(` ${DOCUMENTS_SEEN_SENTENCE}`, ""))
    expect(without[0]).not.toMatch(/looked at documents/i)
    expect(without[0]).toContain("Tutors on Lemely are adults you may not have met.")
    expect(without[0]).toContain("That is not a criminal-records check.")
    expect([...without.slice(1)]).toEqual(notice.paragraphs.slice(1))
    expect(without.join(" ")).not.toContain(DOCUMENTS_SEEN_SENTENCE)
  })

  it("fails closed: no claim about documents unless documentsSeen is exactly true", () => {
    for (const value of [undefined, null, false, 0, "true", 1] as unknown[]) {
      expect(safetyNoticeParagraphs(value as boolean).join(" "), String(value)).not.toMatch(/looked at documents/i)
    }
  })

  it("names the secondary action 'Not now'", () => {
    expect(SAFETY_NOTICE_NOT_NOW).toBe("Not now")
  })

  it("keeps the Egyptian Child Helpline number the SPEC gives", () => {
    expect(SAFETY_NOTICE_PARAGRAPHS.join(" ")).toContain("call 16000 (Child Helpline, Egypt)")
  })
})

describe("C-21 fixed lines", () => {
  const row = SPEC.split("\n").find((line) => line.startsWith("| C-21 |")) ?? ""
  const quoted = [...row.matchAll(/"([^"]+)"/g)].map((m) => m[1])

  it("finds the four quoted lines in the SPEC row", () => {
    expect(quoted).toHaveLength(4)
  })

  it("each constant is one of them, word for word", () => {
    for (const line of [
      NOTES_HIDDEN_PLACEHOLDER,
      NOTES_FIXED_LINE,
      NOTES_TUTOR_PARENTS_LINE,
      NOTES_FROZEN_LINE,
    ]) {
      expect(quoted).toContain(line)
    }
    expect(new Set([NOTES_HIDDEN_PLACEHOLDER, NOTES_FIXED_LINE, NOTES_TUTOR_PARENTS_LINE, NOTES_FROZEN_LINE]).size).toBe(4)
  })
})

describe("contact details refusal", () => {
  const refused = (): ApiError =>
    new ApiError(422, "HTTP 422", { code: "contact_details_not_allowed", message: "x" })

  it("is the sentence SPEC section d prescribes", () => {
    expect(SPEC).toContain(`"${CONTACT_DETAILS_MESSAGE}"`)
  })

  it("has a notes variant that is that sentence without its pointer to the notes", () => {
    expect(NOTES_CONTACT_DETAILS_MESSAGE).not.toBe(CONTACT_DETAILS_MESSAGE)
    expect(CONTACT_DETAILS_MESSAGE.startsWith(NOTES_CONTACT_DETAILS_MESSAGE)).toBe(true)
    expect(NOTES_CONTACT_DETAILS_MESSAGE).not.toMatch(/notes/i)
  })

  it("a safety sheet shows the SPEC sentence for a refused contact detail", () => {
    expect(safetyActionError(refused(), "fallback")).toBe(CONTACT_DETAILS_MESSAGE)
  })

  it("the notes composer's variant replaces it, and only for that code", () => {
    expect(safetyActionError(refused(), "fallback", NOTES_CONTACT_DETAILS_MESSAGE)).toBe(
      NOTES_CONTACT_DETAILS_MESSAGE,
    )
    const other = new ApiError(409, "HTTP 409", { code: "report_exists", message: "x" })
    expect(safetyActionError(other, "fallback", NOTES_CONTACT_DETAILS_MESSAGE)).toBe(
      "You have already reported this.",
    )
  })
})

describe("C-21 foot of the thread", () => {
  const base = { viewer: "student", canPost: true, frozen: false, loading: false, canSend: true } as const

  it("a frozen thread has no composer, whoever is looking and whatever the API allows", () => {
    for (const viewer of ["student", "tutor", "parent"] as const) {
      const state = notesComposerState({ ...base, viewer, frozen: true })
      expect(state.composer, viewer).toBe(false)
      expect(state.tutorParentsLine, viewer).toBe(false)
      expect(state.frozenLine, viewer).toBe(true)
    }
  })

  it("the parents-can-read line goes with a tutor's composer and with nobody else's", () => {
    expect(notesComposerState({ ...base, viewer: "tutor" })).toMatchObject({
      composer: true,
      tutorParentsLine: true,
    })
    expect(notesComposerState({ ...base, viewer: "student" })).toMatchObject({
      composer: true,
      tutorParentsLine: false,
    })
    expect(notesComposerState({ ...base, viewer: "parent" })).toMatchObject({
      composer: false,
      tutorParentsLine: false,
    })
  })

  it("the line is tied to the composer: a tutor who cannot post sees no line about parents", () => {
    const state = notesComposerState({ ...base, viewer: "tutor", canPost: false })
    expect(state.composer).toBe(false)
    expect(state.tutorParentsLine).toBe(false)
    expect(state.closedLine).toBe(true)
  })

  it("a parent never gets a composer or a closed-notes line, only the thread", () => {
    expect(notesComposerState({ ...base, viewer: "parent", canPost: false })).toEqual({
      composer: false,
      tutorParentsLine: false,
      frozenLine: false,
      closedLine: false,
    })
  })

  it("a thread with no way to post shows no composer and no closed line when posting is allowed", () => {
    expect(notesComposerState({ ...base, canSend: false })).toMatchObject({
      composer: false,
      closedLine: false,
    })
  })

  it("keeps the author's words when a post is refused, and lets them go when it succeeds", async () => {
    await expect(sendNoteDraft(() => Promise.resolve("ok"), "hello")).resolves.toBe(true)
    await expect(sendNoteDraft(() => Promise.reject(new Error("refused")), "hello")).resolves.toBe(false)
  })

  it("hands the post the text it was given", async () => {
    const seen: string[] = []
    await sendNoteDraft((body) => {
      seen.push(body)
      return Promise.resolve()
    }, "a note")
    expect(seen).toEqual(["a note"])
  })
})

describe("report details limit", () => {
  const migration = readFileSync(
    join(import.meta.dirname, "..", "..", "..", "lemely", "db", "migrations", "versions", "0050_tutoring_safety.py"),
    "utf8",
  )
  const model = readFileSync(
    join(import.meta.dirname, "..", "..", "..", "lemely", "db", "models", "tutoring.py"),
    "utf8",
  )

  it("is the limit of ck_tutoring_reports_details_len in migration 0050", () => {
    const limit = /char_length\(details\) <= (\d+)",\s*name=op\.f\("ck_tutoring_reports_details_len"\)/.exec(migration)?.[1]
    expect(limit).toBeDefined()
    expect(REPORT_DETAILS_MAX).toBe(Number(limit))
  })

  it("is the limit the model's CHECK states", () => {
    const limit = /char_length\(details\) <= (\d+)", name="details_len"/.exec(model)?.[1]
    expect(limit).toBeDefined()
    expect(REPORT_DETAILS_MAX).toBe(Number(limit))
  })

  it("shows the helpline beside a safety concern and on its receipt, and for nothing else", () => {
    expect(reportShowsHelpline("safety_concern")).toBe(true)
    expect(reportShowsHelpline(null)).toBe(false)
    for (const reason of REPORT_REASONS.map((r) => r.value).filter((v) => v !== "safety_concern")) {
      expect(reportShowsHelpline(reason), reason).toBe(false)
    }
  })
})

describe("report reasons", () => {
  const row = SPEC.split("\n").find((line) => line.startsWith("| `reportreason` |")) ?? ""
  const specReasons = [...(row.split("|")[2] ?? "").matchAll(/`([a-z_]+)`/g)].map((m) => m[1])

  it("offers exactly the seven reasons of the reportreason enum", () => {
    expect(specReasons).toHaveLength(7)
    expect(REPORT_REASONS.map((r) => r.value).sort()).toEqual([...specReasons].sort())
  })

  it("every reason has a plain-language label", () => {
    for (const reason of REPORT_REASONS) {
      expect(reason.label.trim().length).toBeGreaterThan(0)
      expect(reason.label).not.toContain("_")
    }
  })

  it("offers the disputed outcome only on a booking, worded as the SPEC words it", () => {
    expect(SPEC).toContain(`"The session outcome is wrong"`)
    const onBooking = reportReasonsFor("booking")
    expect(onBooking.find((r) => r.value === "disputed_outcome")?.label).toBe(
      "The session outcome is wrong",
    )
    for (const target of ["tutor_profile", "review", "review_reply", "booking_note"] as const) {
      expect(reportReasonsFor(target).some((r) => r.value === "disputed_outcome")).toBe(false)
    }
  })

  it("puts the safety concern first, as the admin queue does", () => {
    expect(reportReasonsFor("tutor_profile")[0].value).toBe("safety_concern")
  })
})

describe("block copy", () => {
  it("states the effects SPEC section a.2 lists, for a student blocking a tutor", () => {
    const copy = blockCopy("student", "Sara A.")
    expect(copy.title).toBe("Block Sara A.?")
    const lines = copy.effects.join(" ")
    expect(lines).toMatch(/future sessions/i)
    expect(lines).toMatch(/less than 24 hours/i)
    expect(lines).toMatch(/progress/i)
    expect(lines).toMatch(/class/i)
    expect(lines).toMatch(/notes/i)
    expect(lines).toMatch(/report/i)
  })

  it("is worded for a tutor blocking a student, and says the sweep also removes the student from the tutor's classes", () => {
    const copy = blockCopy("tutor", "Student 4F2A")
    expect(copy.title).toBe("Block Student 4F2A?")
    const lines = copy.effects.join(" ")
    expect(lines).toMatch(/future sessions with this student/i)
    expect(lines).toMatch(/one of your independent classes/i)
    expect(lines).not.toMatch(/you leave/i)
  })

  // What a block removes is the SPEC's own list (section a.2, "tutoring_blocks"):
  // the live grant and the school-less enrolments. School classes are untouched.
  const BLOCK_ROW = SPEC.split("\n").find((line) => line.includes("Effects of a new or renewed block")) ?? ""

  it("finds the SPEC's list of what a block deletes", () => {
    expect(BLOCK_ROW).toContain("revoke the live grant")
    expect(BLOCK_ROW).toContain("classes.school_id IS NULL")
    expect(SPEC).toContain("so they still see your class progress there")
  })

  it("does not say a block ends all sight of the student's progress: school classes keep theirs", () => {
    const student = blockCopy("student", "X").effects
    const sight = student.find((line) => /seeing your progress/i.test(line)) ?? ""
    expect(sight).toContain("through Lemely's tutoring pages")
    expect(sight).toContain("If they teach one of your school classes, they still see your progress there.")

    const tutor = blockCopy("tutor", "X").effects
    const tutorSight = tutor.find((line) => /seeing their progress/i.test(line)) ?? ""
    expect(tutorSight).toContain("through Lemely's tutoring pages")
    expect(tutorSight).toContain("If they are in one of your school classes, you still see their progress there.")
  })

  it("never claims the sight stops outright", () => {
    for (const viewer of ["student", "tutor"] as const) {
      const lines = blockCopy(viewer, "X").effects.join(" ")
      expect(lines).not.toMatch(/(?:They|You) stop seeing (?:your|their) progress[,.]/)
    }
  })

  it("tells a student their grades stop counting, which a student's own block does and a tutor's does not", () => {
    expect(blockCopy("student", "X").effects).toContain("Your grades stop counting in their results.")
    expect(blockCopy("tutor", "X").effects.join(" ")).not.toMatch(/grades/i)
  })

  it("says unblocking restores nothing, as route B3 does", () => {
    for (const viewer of ["student", "tutor"] as const) {
      expect(blockCopy(viewer, "X").effects.at(-1)).toMatch(/unblock/i)
      expect(blockCopy(viewer, "X").effects.at(-1)).toMatch(/won't bring any of this back/)
    }
  })

  it("has a confirm and a cancel that name what they do", () => {
    const copy = blockCopy("student", "Sara A.")
    expect(copy.confirmLabel).toBe("Block")
    expect(copy.cancelLabel).not.toBe("Cancel")
  })
})

describe("copy rule", () => {
  it("none of the safety copy uses a banned tutoring word", () => {
    const all = [
      SAFETY_NOTICE_TITLE,
      ...SAFETY_NOTICE_PARAGRAPHS,
      SAFETY_NOTICE_BUTTON,
      SAFETY_NOTICE_NOT_NOW,
      ...safetyNoticeParagraphs(false),
      NOTES_FIXED_LINE,
      NOTES_TUTOR_PARENTS_LINE,
      NOTES_FROZEN_LINE,
      NOTES_HIDDEN_PLACEHOLDER,
      CONTACT_DETAILS_MESSAGE,
      NOTES_CONTACT_DETAILS_MESSAGE,
      ...REPORT_REASONS.map((r) => r.label),
      ...blockCopy("student", "X").effects,
      ...blockCopy("tutor", "X").effects,
    ].join(" ")
    expect(all).not.toMatch(/\b(?:improvements?|verified)\b/i)
  })
})

describe("safetyActionError", () => {
  const api = (status: number, code: string): ApiError =>
    new ApiError(status, `HTTP ${status}`, { code, message: "x" })

  it("uses the typed sentence for a code the tutoring API sent", () => {
    expect(safetyActionError(api(409, "report_exists"), "fallback")).toBe(
      "You have already reported this.",
    )
  })

  it("falls back for anything else, and says nothing for no error", () => {
    expect(safetyActionError(new Error("boom"), "We couldn't send that. Try again.")).toBe(
      "We couldn't send that. Try again.",
    )
    expect(safetyActionError(null, "fallback")).toBeNull()
    expect(safetyActionError(undefined, "fallback")).toBeNull()
  })
})

describe("component sources", () => {
  const read = (...parts: string[]) =>
    stripComments(readFileSync(join(import.meta.dirname, "..", "..", "src", ...parts), "utf8"))

  it("C-24 sheet cannot be dismissed without the button and calls onAcknowledge", () => {
    const source = read("components", "ui", "safety-notice-sheet.tsx")
    expect(source).toContain("dismissible={false}")
    expect(source).toContain("hideCloseButton")
    expect(source).toContain("onAcknowledge")
    // The paragraphs come from the shared copy module (`safetyNoticeParagraphs` maps SAFETY_NOTICE_PARAGRAPHS).
    expect(source).toContain("safetyNoticeParagraphs(")
    expect(source).not.toMatch(/^\s*["'`]Tutors on Lemely/m)
  })

  it("C-24 sheet offers 'Not now' only when the screen gives it a way out, and Not now never acknowledges", () => {
    const source = read("components", "ui", "safety-notice-sheet.tsx")
    expect(source).toContain("onNotNow")
    expect(source).toContain("SAFETY_NOTICE_NOT_NOW")
    expect(source).toMatch(/onNotNow\s*\?/)
    // The extra button is wired to onNotNow and the primary one alone to onAcknowledge.
    expect(source.match(/onClick=\{onAcknowledge\}/g)).toHaveLength(1)
    expect(source).toMatch(/onClick=\{onNotNow\}/)
    // Still not dismissible by Escape or the scrim: the button is the only way out.
    expect(source).toContain("dismissible={false}")
    expect(source).toContain("hideCloseButton")
    expect(source).toContain("documentsSeen")
    expect(source).toContain("safetyNoticeParagraphs(")
  })

  it("S-35 passes the tutor's documentsSeen and a Not now that leaves the page without acknowledging", () => {
    const source = read("portals", "student", "screens", "tutoring", "BookSession.tsx")
    expect(source).toContain("documentsSeen={tutor.documentsSeen}")
    const notNow = /onNotNow=\{([\s\S]*?)\}\s*\n\s*(?:documentsSeen|onAcknowledge|\/>)/.exec(source)
    expect(notNow, "onNotNow is not wired").not.toBeNull()
    expect(notNow![1]).toContain("navigate(")
    expect(notNow![1]).not.toContain("acknowledge")
  })

  it("C-24 sheet puts the five paragraphs in the Modal's description, so a screen reader hears them before the button", () => {
    const source = read("components", "ui", "safety-notice-sheet.tsx")
    const description = source.indexOf("description={")
    const paragraphs = source.indexOf("safetyNoticeParagraphs(documentsSeen).map")
    const footer = source.indexOf("footer={")
    expect(description).toBeGreaterThan(-1)
    expect(paragraphs).toBeGreaterThan(description)
    expect(footer).toBeGreaterThan(paragraphs)
  })

  it("C-21 asks the shared rules what to show and wires the notes variant of the contact-details refusal", () => {
    const source = read("components", "ui", "notes-thread.tsx")
    expect(source).toContain("notesComposerState(")
    expect(source).toContain("sendNoteDraft(")
    expect(source).toContain("NOTES_CONTACT_DETAILS_MESSAGE")
    expect(source).toMatch(/onPost\?: \(body: string\) => Promise<unknown>/)
    // The line about parents is drawn from the rule, never from the viewer directly.
    expect(source).toMatch(/\.tutorParentsLine\s*\?/)
    expect(source).not.toMatch(/viewer === "tutor"/)
  })

  it("C-21 shows a refused contact detail on the field and any other failure as an alert", () => {
    const source = read("components", "ui", "notes-thread.tsx")
    expect(source).toContain('isTutoringError(postError, "contact_details_not_allowed")')
    expect(source).toContain('role="alert"')
  })

  it("every other free-text sheet keeps the SPEC sentence: none overrides it", () => {
    for (const file of ["report-sheet.tsx", "block-sheet.tsx"]) {
      const source = read("components", "tutoring", file)
      expect(source, file).not.toContain("NOTES_CONTACT_DETAILS_MESSAGE")
    }
    expect(read("components", "ui", "safety-notice-sheet.tsx")).not.toContain("NOTES_CONTACT_DETAILS_MESSAGE")
  })

  it("the report sheet reports a failure in an alert, not on the optional field, and keeps the helpline on its receipt", () => {
    const source = read("components", "tutoring", "report-sheet.tsx")
    expect(source).toContain('role="alert"')
    // Without this the slice below would be (-1, -1) and the next assertion would pass on an empty string.
    expect(source.indexOf("<Textarea")).toBeGreaterThan(-1)
    const textarea = source.slice(source.indexOf("<Textarea"), source.indexOf("/>", source.indexOf("<Textarea")))
    expect(textarea.length).toBeGreaterThan("<Textarea".length)
    expect(textarea).not.toMatch(/\berror=/)
    expect(source.match(/reportShowsHelpline\(/g)?.length).toBeGreaterThanOrEqual(2)
    // The receipt (the `sent` view) comes first in the file and must carry the line too.
    const receipt = source.slice(source.indexOf("if (sent)"), source.indexOf("const trimmed"))
    expect(receipt).toContain("HELPLINE_LINE")
  })

  it("the report and block sheets live in components/tutoring and use the shared Modal", () => {
    for (const file of ["report-sheet.tsx", "block-sheet.tsx"]) {
      const source = read("components", "tutoring", file)
      expect(source).toContain('from "@/components/ui/modal"')
    }
  })
})
