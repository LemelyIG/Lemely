import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { stripComments } from "./support/jsxSource"
import {
  CONTACT_DETAILS_MESSAGE,
  NOTES_FIXED_LINE,
  NOTES_FROZEN_LINE,
  NOTES_HIDDEN_PLACEHOLDER,
  NOTES_TUTOR_PARENTS_LINE,
  REPORT_REASONS,
  SAFETY_NOTICE_BUTTON,
  SAFETY_NOTICE_PARAGRAPHS,
  SAFETY_NOTICE_TITLE,
  blockCopy,
  reportReasonsFor,
  safetyActionError,
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
  it("is the sentence SPEC section d prescribes", () => {
    expect(SPEC).toContain(`"${CONTACT_DETAILS_MESSAGE}"`)
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
      NOTES_FIXED_LINE,
      NOTES_TUTOR_PARENTS_LINE,
      NOTES_FROZEN_LINE,
      NOTES_HIDDEN_PLACEHOLDER,
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
    expect(source).toContain("SAFETY_NOTICE_PARAGRAPHS")
  })

  it("the report and block sheets live in components/tutoring and use the shared Modal", () => {
    for (const file of ["report-sheet.tsx", "block-sheet.tsx"]) {
      const source = read("components", "tutoring", file)
      expect(source).toContain('from "@/components/ui/modal"')
    }
  })
})
