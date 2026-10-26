import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import {
  ACCOUNT_TOO_NEW_LINE,
  CANCEL_RULE_LINE,
  COMPLETE_HINT,
  COUNTING_NOTICE,
  REVIEW_EDIT_RECHECK_LINE,
  REVIEW_PRIVACY_LINE,
  REVIEW_TEXT_MAX,
  REVIEW_UNAVAILABLE_LINE,
  REASON_LABEL,
  SESSION_ZONE_LABEL,
  cancelledNotice,
  formatTutorDate,
  insideCancelWindowNotice,
  mergePages,
  noteNeedsSafetyNotice,
  parentNotesFootnote,
  reviewCreateBody,
  reviewEditHint,
  reviewStatusLine,
  reviewUpdateBody,
  reviewView,
  safeMeetingHref,
  sessionActionError,
  sessionActions,
  sessionPlace,
  sessionRowView,
  sessionTimeLabel,
  showCountingNotice,
  stateNotice,
  type SessionViewer,
} from "@/lib/tutoring/sessionView"
import type { Booking, EffectiveState, ViewerAction } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * T23 · S-36 / S-37 logic (SPEC §d, §a.3, §i.8). The fixed sentences are parsed
 * out of the SPEC text, so a wording change has to start there; the expected
 * side of every test is derived from the SPEC or from an independent
 * computation, never from a second copy of the constant under test.
 */

const WEB = join(import.meta.dirname, "..", "..")
const REPO = join(WEB, "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")

function specBlock(startMarker: string, endMarker: string): string {
  const start = SPEC.indexOf(startMarker)
  expect(start, startMarker).toBeGreaterThan(-1)
  const end = SPEC.indexOf(endMarker, start)
  expect(end, endMarker).toBeGreaterThan(start)
  return SPEC.slice(start, end)
}

const S37 = specBlock("**S-37 · Session detail**", "**S-38 · Tutors & your data**")
const S35 = specBlock("**S-35 · Book a session**", "**S-36 · My sessions**")

/** The first double-quoted string that follows `anchor` in `block`. */
function quotedAfter(block: string, anchor: string): string {
  const at = block.indexOf(anchor)
  expect(at, `anchor not in SPEC: ${anchor}`).toBeGreaterThan(-1)
  const open = block.indexOf('"', at + anchor.length)
  const close = block.indexOf('"', open + 1)
  expect(open).toBeGreaterThan(-1)
  expect(close).toBeGreaterThan(open)
  return block.slice(open + 1, close)
}

// Labels with no year are right only in the current year (Cairo zone). The
// fixtures are all January 2026, so the clock the label compares against is
// pinned inside that year; tests of the year rule pass their own `nowMs`.
beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date("2026-01-05T09:00:00Z"))
})
afterAll(() => {
  vi.useRealTimers()
})

// ── Fixtures ────────────────────────────────────────────────────────────────

// 2026-01-08 is a Thursday and Cairo is UTC+2 then.
const STARTS = "2026-01-08T15:00:00Z"
const ENDS = "2026-01-08T16:00:00Z"
const START_MS = Date.parse(STARTS)
const HOUR = 3_600_000

function booking(overrides: Partial<Booking> = {}): Booking {
  return {
    bookingId: "b1",
    tutor: {
      tutorId: "t1",
      publicName: "Nour A.",
      headline: "IGCSE Maths",
      subjects: [{ code: "0580", name: "Mathematics" }],
      modes: ["virtual"],
      area: { code: "maadi", name: "Maadi" },
      rating: { state: "new", average: null, count: 0 },
    },
    student: { studentId: "s1", displayName: "Maya R." },
    requestedBy: "student",
    subject: { code: "0580", name: "Mathematics" },
    mode: "virtual",
    startsAt: STARTS,
    endsAt: ENDS,
    effectiveState: "accepted",
    area: { code: "maadi", name: "Maadi" },
    meetingLink: null,
    locationDetail: null,
    otherModeNote: null,
    declineReason: null,
    cancelReason: null,
    cancelledBy: null,
    cancelledLate: false,
    completedBy: null,
    notesFrozen: false,
    allowedActions: [],
    review: null,
    reviewOpensAt: null,
    studentShared: null,
    createdAt: "2026-01-01T10:00:00Z",
    ...overrides,
  }
}

const ALL_ACTIONS: ViewerAction[] = [
  "accept",
  "decline",
  "cancel",
  "cancel_with_reason",
  "complete",
  "no_show",
  "review",
  "post_note",
]

function coded(status: number, code: string): ApiError {
  const error = new ApiError(status, code)
  error.detail = { code, message: "server words that must not be shown" }
  return error
}

// ── Actions come from allowedActions and from nothing else ────────────────

describe("sessionActions: rendered only from allowedActions", () => {
  it("knows all eight ViewerAction values (parsed from SPEC b.3)", () => {
    const line = SPEC.split("\n").find((l) => l.startsWith("ViewerActionLit")) ?? ""
    const next = SPEC.split("\n")[SPEC.split("\n").indexOf(line) + 1] ?? ""
    const specActions = [...(line + next).matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
    expect(specActions.sort()).toEqual([...ALL_ACTIONS].sort())
  })

  it("an empty allowedActions renders nothing, whatever the state", () => {
    const states: EffectiveState[] = [
      "requested",
      "accepted",
      "awaiting_outcome",
      "completed",
      "declined",
      "cancelled",
      "no_show",
      "expired",
    ]
    for (const effectiveState of states) {
      expect(sessionActions(booking({ effectiveState, allowedActions: [] }), "student")).toEqual({
        cancel: false,
        complete: false,
        review: false,
        postNote: false,
      })
    }
  })

  it("each action alone switches on exactly its own control for a student", () => {
    const expected: Record<ViewerAction, Partial<ReturnType<typeof sessionActions>>> = {
      accept: {},
      decline: {},
      cancel: { cancel: true },
      cancel_with_reason: {},
      complete: { complete: true },
      no_show: {},
      review: { review: true },
      post_note: { postNote: true },
    }
    for (const action of ALL_ACTIONS) {
      const got = sessionActions(booking({ allowedActions: [action] }), "student")
      expect(got, action).toEqual({
        cancel: false,
        complete: false,
        review: false,
        postNote: false,
        ...expected[action],
      })
    }
  })

  it("a tutor-only action is never rendered for a student or a parent", () => {
    for (const viewer of ["student", "parent"] as const) {
      const got = sessionActions(
        booking({ requestedBy: "parent", allowedActions: ["accept", "decline", "cancel_with_reason", "no_show"] }),
        viewer,
      )
      expect(got.cancel).toBe(false)
      expect(got.complete).toBe(false)
    }
  })

  it("a control is not inferred from the state: an accepted booking without cancel has no Cancel", () => {
    expect(sessionActions(booking({ effectiveState: "accepted", allowedActions: [] }), "student").cancel).toBe(false)
    expect(sessionActions(booking({ effectiveState: "awaiting_outcome", allowedActions: [] }), "student").complete).toBe(
      false,
    )
  })

  it("a parent acts only on a booking they requested, and only when the API allows it", () => {
    const allowed: ViewerAction[] = ["cancel", "complete", "review", "post_note"]
    const requested = sessionActions(booking({ requestedBy: "parent", allowedActions: allowed }), "parent")
    expect(requested).toEqual({ cancel: true, complete: true, review: false, postNote: false })
    const notRequested = sessionActions(booking({ requestedBy: "student", allowedActions: allowed }), "parent")
    expect(notRequested).toEqual({ cancel: false, complete: false, review: false, postNote: false })
    const notAllowed = sessionActions(booking({ requestedBy: "parent", allowedActions: [] }), "parent")
    expect(notAllowed.cancel).toBe(false)
  })
})

// ── Inside 24 hours ───────────────────────────────────────────────────────

describe("insideCancelWindowNotice", () => {
  const specLine = quotedAfter(S37, "Inside 24 h:")
  const withNotes = booking({ allowedActions: ["post_note"] })

  it("reads the SPEC sentence for a student inside the window", () => {
    expect(specLine).toContain("less than 24 hours")
    expect(insideCancelWindowNotice(withNotes, "student", START_MS - 10 * HOUR)).toBe(specLine)
  })

  it("is silent outside the window, after the start, and when the API still allows Cancel", () => {
    expect(insideCancelWindowNotice(withNotes, "student", START_MS - 30 * HOUR)).toBeNull()
    expect(insideCancelWindowNotice(withNotes, "student", START_MS + HOUR)).toBeNull()
    expect(
      insideCancelWindowNotice(booking({ allowedActions: ["cancel", "post_note"] }), "student", START_MS - 10 * HOUR),
    ).toBeNull()
  })

  it("applies to a confirmed session only", () => {
    for (const effectiveState of ["requested", "completed", "cancelled", "declined", "expired"] as const) {
      expect(insideCancelWindowNotice(booking({ effectiveState }), "student", START_MS - 10 * HOUR), effectiveState).toBeNull()
    }
  })

  it("does not send the student to a tutor they cannot message", () => {
    const text = insideCancelWindowNotice(booking({ allowedActions: [] }), "student", START_MS - 10 * HOUR)
    expect(text).toBe("It's less than 24 hours to the start, so you can't cancel this session.")
  })

  it("a parent hears it only for a booking they requested, and is not told to message", () => {
    const own = booking({ requestedBy: "parent" })
    const text = insideCancelWindowNotice(own, "parent", START_MS - 10 * HOUR)
    expect(text).not.toBeNull()
    expect(text).not.toMatch(/message/i)
    expect(insideCancelWindowNotice(booking({ requestedBy: "student" }), "parent", START_MS - 10 * HOUR)).toBeNull()
  })

  it("the cancel rule line is the SPEC's", () => {
    expect(CANCEL_RULE_LINE).toBe(quotedAfter(S37, "Cancel ("))
  })
})

// ── Cancelled, declined, expired and the rest ─────────────────────────────

describe("cancelledNotice: late cancel by the tutor", () => {
  const template = quotedAfter(S37, "Cancelled late by the tutor")

  it("is the SPEC sentence with the reason after it", () => {
    const got = cancelledNotice(
      booking({
        effectiveState: "cancelled",
        cancelledBy: "tutor",
        cancelledLate: true,
        cancelReason: "I am unwell",
      }),
      "student",
    )
    const joined = `${got?.lead} ${REASON_LABEL} ${got?.reason}`
    expect(joined).toBe(template.replace("{Tutor}", "Nour A.").replace("{cancelReason}", "I am unwell"))
  })

  it("keeps the reason as plain text: no escaping, no stripping, no parsing", () => {
    const hostile = `<img src=x onerror="alert(1)"> &amp; <b>bold</b> https://example.com`
    const got = cancelledNotice(
      booking({ effectiveState: "cancelled", cancelledBy: "tutor", cancelledLate: true, cancelReason: hostile }),
      "student",
    )
    expect(got?.reason).toBe(hostile)
  })

  it("says nothing about a reason that was not given", () => {
    const got = cancelledNotice(
      booking({ effectiveState: "cancelled", cancelledBy: "tutor", cancelledLate: true, cancelReason: null }),
      "student",
    )
    expect(got?.reason).toBeNull()
    expect(got?.lead).toContain("less than 24 hours before the start")
  })

  it("a tutor cancellation outside the window is not described as late", () => {
    const got = cancelledNotice(
      booking({ effectiveState: "cancelled", cancelledBy: "tutor", cancelledLate: false, cancelReason: null }),
      "student",
    )
    expect(got?.lead).toBe("Nour A. cancelled this session.")
  })

  it("a parent reads the same facts, with the tutor's reason", () => {
    const got = cancelledNotice(
      booking({ effectiveState: "cancelled", cancelledBy: "tutor", cancelledLate: true, cancelReason: "Ill" }),
      "parent",
    )
    expect(got?.reason).toBe("Ill")
  })
})

describe("cancelledNotice: the platform is the only voice for a system cancellation (SPEC i.8)", () => {
  const FORBIDDEN = /block|suspend|clos(?:e|ed|ing)|report|safety|banned|removed|reason|because/i

  for (const cancelledBy of ["system", "platform_admin"] as const) {
    for (const viewer of ["student", "parent"] as SessionViewer[]) {
      it(`${cancelledBy} reads as Lemely to a ${viewer}, and never repeats the stored reason`, () => {
        const got = cancelledNotice(
          booking({
            effectiveState: "cancelled",
            cancelledBy,
            cancelReason: "The tutor blocked the student after a safety report",
          }),
          viewer,
        )
        expect(got?.lead).toBe("This session was cancelled by Lemely.")
        expect(got?.reason).toBeNull()
        expect(got?.lead).not.toMatch(FORBIDDEN)
      })
    }
  }

  it("no notice, for any state or viewer, names a block or a suspension", () => {
    const states: EffectiveState[] = ["requested", "declined", "cancelled", "expired", "no_show", "awaiting_outcome"]
    for (const viewer of ["student", "parent"] as SessionViewer[]) {
      for (const effectiveState of states) {
        const got = stateNotice(
          booking({ effectiveState, cancelledBy: "system", cancelReason: "blocked", declineReason: null }),
          viewer,
        )
        const text = `${got?.lead ?? ""} ${got?.reason ?? ""}`
        expect(text, `${viewer}/${effectiveState}`).not.toMatch(/block|suspend|banned/i)
      }
    }
  })

  it("who cancelled a student's own booking is told plainly", () => {
    const base = { effectiveState: "cancelled" as const }
    expect(cancelledNotice(booking({ ...base, cancelledBy: "student" }), "student")?.lead).toBe(
      "You cancelled this session.",
    )
    expect(cancelledNotice(booking({ ...base, cancelledBy: "parent" }), "student")?.lead).toBe(
      "A parent cancelled this session.",
    )
    expect(cancelledNotice(booking({ ...base, cancelledBy: "student" }), "parent")?.lead).toBe(
      "Maya R. cancelled this session.",
    )
    expect(cancelledNotice(booking({ ...base, cancelledBy: null }), "student")?.lead).toBe(
      "This session was cancelled.",
    )
  })

  it("returns nothing for a booking that was not cancelled", () => {
    expect(cancelledNotice(booking({ effectiveState: "completed" }), "student")).toBeNull()
  })
})

describe("stateNotice", () => {
  it("expired reads the SPEC sentence", () => {
    const got = stateNotice(booking({ effectiveState: "expired" }), "student")
    expect(got?.lead).toBe(quotedAfter(S37, "Expired request:"))
  })

  it("a declined request names the tutor and keeps their reason as given", () => {
    const got = stateNotice(
      booking({ effectiveState: "declined", declineReason: "<i>Fully booked</i>" }),
      "student",
    )
    expect(got?.lead).toBe("Nour A. declined this request.")
    expect(got?.reason).toBe("<i>Fully booked</i>")
  })

  it("a waiting request says who it is waiting for", () => {
    expect(stateNotice(booking({ effectiveState: "requested" }), "student")?.lead).toBe(
      "Your request is waiting for Nour A. to reply.",
    )
  })

  it("a no-show points at Report, without blame", () => {
    const got = stateNotice(booking({ effectiveState: "no_show" }), "student")
    expect(got?.lead).toContain("no-show")
    expect(got?.lead).toContain("The session outcome is wrong")
  })

  it("confirmed and completed sessions need no notice", () => {
    expect(stateNotice(booking({ effectiveState: "accepted" }), "student")).toBeNull()
    expect(stateNotice(booking({ effectiveState: "completed" }), "student")).toBeNull()
  })

  it("the complete hint is the SPEC's", () => {
    expect(COMPLETE_HINT).toBe(quotedAfter(S37, '"Mark as completed" when `awaiting_outcome` ≥ 48 h ('))
  })
})

// ── Reviews ───────────────────────────────────────────────────────────────

describe("reviewView", () => {
  const done = { effectiveState: "completed" as const }

  it("offers the form only when the API allows a review", () => {
    expect(reviewView(booking({ ...done, allowedActions: ["review"] }), "student", START_MS + 9 * 24 * HOUR)).toEqual({
      kind: "write",
    })
    expect(reviewView(booking({ ...done, allowedActions: [] }), "student", START_MS + 9 * 24 * HOUR)).toBeNull()
  })

  it("before the window opens it says when, in the tutor's zone (SPEC wording)", () => {
    const opens = "2026-01-15T16:00:00Z"
    const got = reviewView(booking({ ...done, reviewOpensAt: opens }), "student", START_MS + 2 * 24 * HOUR)
    expect(got).toEqual({ kind: "opens", line: "You can review this session from 15 Jan 2026." })
    expect(quotedAfter(S37, "Review (from `reviewOpensAt`:")).toBe("You can review this session from {date}.")
  })

  it("a review in the evening Cairo time belongs to the Cairo day, not the UTC one", () => {
    expect(formatTutorDate("2026-01-15T22:30:00Z")).toBe("16 Jan 2026")
    expect(formatTutorDate("2026-07-15T21:30:00Z")).toBe("16 Jul 2026")
  })

  it("once the window is open, a missing Review action is not explained by guessing", () => {
    // The server withholds Review for a young account, but also after an admin
    // removed the review. A line naming the account would be false for the
    // second student, so the view says only what is certain.
    const opened = booking({ ...done, allowedActions: [], reviewOpensAt: "2026-01-15T16:00:00Z" })
    const got = reviewView(opened, "student", Date.parse("2026-01-20T00:00:00Z"))
    expect(got).toEqual({ kind: "unavailable", line: REVIEW_UNAVAILABLE_LINE })
    expect(REVIEW_UNAVAILABLE_LINE).toBe("You can't review this session right now.")
    expect(JSON.stringify(got)).not.toMatch(/account|14 days/i)
    expect(reviewView(opened, "parent", Date.parse("2026-01-20T00:00:00Z"))).toBeNull()
  })

  it("the account line is reserved for the server's 409 account_too_new, and stays the SPEC's", () => {
    expect(sessionActionError(coded(409, "account_too_new"), "review")).toBe(ACCOUNT_TOO_NEW_LINE)
    const opened = booking({ ...done, allowedActions: [], reviewOpensAt: "2026-01-15T16:00:00Z" })
    const got = reviewView(opened, "student", Date.parse("2026-01-20T00:00:00Z"))
    expect(got && "line" in got ? got.line : "").not.toBe(ACCOUNT_TOO_NEW_LINE)
  })

  it("an existing review can be changed until editableUntil, and only by the student", () => {
    const review = { reviewId: "r1", stars: 4, textState: "pending" as const, editableUntil: "2026-01-30T00:00:00Z" }
    const mine = booking({ ...done, review, allowedActions: [] })
    expect(reviewView(mine, "student", Date.parse("2026-01-20T00:00:00Z"))).toEqual({
      kind: "existing",
      stars: 4,
      textState: "pending",
      canEdit: true,
    })
    expect(reviewView(mine, "student", Date.parse("2026-02-01T00:00:00Z"))).toMatchObject({ canEdit: false })
    expect(reviewView(mine, "parent", Date.parse("2026-01-20T00:00:00Z"))).toBeNull()
  })

  it("never shows a review area for a booking that is not completed", () => {
    expect(reviewView(booking({ effectiveState: "accepted", reviewOpensAt: "2026-01-15T16:00:00Z" }), "student", START_MS)).toBeNull()
  })

  it("the account-too-new line is the SPEC's and replaces the generic one", () => {
    expect(ACCOUNT_TOO_NEW_LINE).toBe(quotedAfter(S37, "Account too new to review:"))
    expect(sessionActionError(coded(409, "account_too_new"), "review")).toBe(ACCOUNT_TOO_NEW_LINE)
  })

  it("the privacy line under the form is the SPEC's", () => {
    expect(REVIEW_PRIVACY_LINE).toBe(quotedAfter(S37, "Review form: stars, optional text,"))
  })
})

describe("review request bodies", () => {
  it("a new review sends stars and trimmed text, or no text", () => {
    expect(reviewCreateBody(5, "  Clear and patient.  ")).toEqual({ stars: 5, text: "Clear and patient." })
    expect(reviewCreateBody(3, "   ")).toEqual({ stars: 3, text: null })
  })

  it("the text limit is the database's 1000", () => {
    expect(REVIEW_TEXT_MAX).toBe(1000)
  })

  it("an edit sends only what changed", () => {
    expect(reviewUpdateBody({ initialStars: 4, stars: 5, text: "", clearText: false })).toEqual({ stars: 5 })
    expect(reviewUpdateBody({ initialStars: 4, stars: 4, text: " New words ", clearText: false })).toEqual({
      text: "New words",
    })
    expect(reviewUpdateBody({ initialStars: 4, stars: 4, text: "", clearText: true })).toEqual({ clearText: true })
  })

  it("clearing wins over typed text, and an unchanged form sends nothing", () => {
    expect(reviewUpdateBody({ initialStars: 4, stars: 4, text: "ignored", clearText: true })).toEqual({ clearText: true })
    expect(reviewUpdateBody({ initialStars: 4, stars: 4, text: "  ", clearText: false })).toBeNull()
  })

  it("each text state has its own plain status line, and none mentions a tutor decision about the stars", () => {
    const lines = (["none", "pending", "approved", "rejected"] as const).map((s) => reviewStatusLine(s))
    expect(new Set(lines).size).toBe(4)
    for (const line of lines) expect(line).not.toMatch(/improv|verified|!/i)
    expect(reviewStatusLine("pending")).toContain("waiting for Lemely")
  })
})

// ── Place, link and counting ──────────────────────────────────────────────

describe("sessionPlace and safeMeetingHref", () => {
  it("links an https meeting link and shows its host", () => {
    expect(sessionPlace(booking({ meetingLink: "https://meet.google.com/abc-defg-hij" }))).toEqual({
      kind: "link",
      href: "https://meet.google.com/abc-defg-hij",
      host: "meet.google.com",
    })
  })

  it("never makes a link out of a script, data or mail address", () => {
    for (const bad of ["javascript:alert(1)", "data:text/html,<b>x</b>", "mailto:a@b.co", "tel:+201000000000", "ftp://x.test/f", "not a url"]) {
      expect(safeMeetingHref(bad), bad).toBeNull()
    }
    expect(safeMeetingHref("http://example.test/room")).toBe("http://example.test/room")
  })

  it("shows an unusable link as text rather than dropping it or linking it", () => {
    expect(sessionPlace(booking({ meetingLink: "javascript:alert(1)" }))).toEqual({
      kind: "text",
      label: "Meeting link",
      text: "javascript:alert(1)",
    })
  })

  it("an in-person session shows the place, an other-mode session shows the tutor's note", () => {
    expect(sessionPlace(booking({ mode: "in_person", locationDetail: "Cafe on Road 9" }))).toEqual({
      kind: "text",
      label: "Meeting place",
      text: "Cafe on Road 9",
    })
    expect(sessionPlace(booking({ mode: "other", otherModeNote: "Phone call" }))).toEqual({
      kind: "text",
      label: "How you will meet",
      text: "Phone call",
    })
  })

  it("shows nothing once a session is cancelled, declined, expired or a no-show", () => {
    for (const effectiveState of ["cancelled", "declined", "expired", "no_show"] as const) {
      expect(sessionPlace(booking({ effectiveState, meetingLink: "https://meet.google.com/x" })), effectiveState).toBeNull()
    }
    expect(sessionPlace(booking({ effectiveState: "completed", meetingLink: "https://meet.google.com/x" }))).not.toBeNull()
  })

  it("shows nothing before the tutor has accepted", () => {
    expect(sessionPlace(booking({ effectiveState: "requested", meetingLink: null }))).toBeNull()
    expect(sessionPlace(booking({ meetingLink: null, locationDetail: null }))).toBeNull()
  })
})

describe("counting notice", () => {
  it("is the SPEC sentence, for a student with a live session only", () => {
    expect(COUNTING_NOTICE).toBe(quotedAfter(S35, "**Counting notice** (row 8b):"))
    expect(showCountingNotice(booking({ effectiveState: "accepted" }), "student")).toBe(true)
    expect(showCountingNotice(booking({ effectiveState: "completed" }), "student")).toBe(true)
    expect(showCountingNotice(booking({ effectiveState: "cancelled" }), "student")).toBe(false)
    expect(showCountingNotice(booking({ effectiveState: "declined" }), "student")).toBe(false)
    expect(showCountingNotice(booking({ effectiveState: "accepted" }), "parent")).toBe(false)
  })
})

// ── Notes ─────────────────────────────────────────────────────────────────

describe("notes and the safety notice (C-21, C-24)", () => {
  it("a student who has not read the notice is held; unknown is not held", () => {
    expect(noteNeedsSafetyNotice("student", false)).toBe(true)
    expect(noteNeedsSafetyNotice("student", true)).toBe(false)
    expect(noteNeedsSafetyNotice("student", null)).toBe(false)
  })

  it("a parent is never shown the notice before a note, because a parent never writes one", () => {
    expect(noteNeedsSafetyNotice("parent", false)).toBe(false)
  })

  it("the parent's read-only line is the SPEC's with the child's name", () => {
    const p06 = specBlock("**P-06 · Session detail (parent, read-only)**", "**P-07")
    const template = quotedAfter(p06, "C-21 read-only (")
    expect(parentNotesFootnote("Maya")).toBe(template.replaceAll("{child}", "Maya"))
  })
})

// ── List rows, times, paging ──────────────────────────────────────────────

describe("sessionTimeLabel: the year appears when it is not this year (Cairo zone)", () => {
  const b = booking()

  it("omits the year in the current year and adds it for another", () => {
    expect(sessionTimeLabel(b, "Africa/Cairo", "Cairo time", Date.parse("2026-06-01T00:00:00Z"))).toBe(
      "Thu 8 Jan · 17:00–18:00 Cairo time",
    )
    expect(sessionTimeLabel(b, "Africa/Cairo", "Cairo time", Date.parse("2027-01-02T00:00:00Z"))).toBe(
      "Thu 8 Jan 2026 · 17:00–18:00 Cairo time",
    )
    expect(sessionTimeLabel(b, "Africa/Cairo", "Cairo time", Date.parse("2025-03-01T00:00:00Z"))).toBe(
      "Thu 8 Jan 2026 · 17:00–18:00 Cairo time",
    )
  })

  it("compares years on the Cairo calendar, not UTC's", () => {
    // 22:30 UTC on 31 Dec 2026 is already 1 Jan 2027 in Cairo.
    const newYear = booking({ startsAt: "2026-12-31T22:30:00Z", endsAt: "2026-12-31T23:30:00Z" })
    expect(sessionTimeLabel(newYear, "Africa/Cairo", "Cairo time", Date.parse("2026-12-31T21:30:00Z"))).toBe(
      "Fri 1 Jan 2027 · 00:30–01:30 Cairo time",
    )
    expect(sessionTimeLabel(newYear, "Africa/Cairo", "Cairo time", Date.parse("2027-02-01T00:00:00Z"))).toBe(
      "Fri 1 Jan · 00:30–01:30 Cairo time",
    )
  })

  it("row labels carry the year too, since they use the same function", () => {
    const old = booking({ startsAt: "2025-12-04T15:00:00Z", endsAt: "2025-12-04T16:00:00Z" })
    expect(sessionRowView(old).timeLabel).toBe("Thu 4 Dec 2025 · 17:00–18:00 Cairo time")
  })
})

describe("reviewEditHint", () => {
  it("warns only when an approved review's text is being replaced", () => {
    expect(REVIEW_EDIT_RECHECK_LINE).toBe("Editing your review sends it back for checking.")
    expect(reviewEditHint("approved", "A better sentence.")).toBe(REVIEW_EDIT_RECHECK_LINE)
    expect(reviewEditHint("approved", "   ")).toBeNull()
    expect(reviewEditHint("approved", "")).toBeNull()
    expect(reviewEditHint("pending", "New text")).toBeNull()
    expect(reviewEditHint("none", "New text")).toBeNull()
    expect(reviewEditHint("rejected", "New text")).toBeNull()
  })

  it("the edit form asks for the hint and is told the text state", () => {
    const form = stripComments(readFileSync(join(WEB, "src/components/tutoring/review-form.tsx"), "utf8"))
    expect(form).toContain("reviewEditHint(props.textState, text)")
    const view = stripComments(readFileSync(join(WEB, "src/components/tutoring/session-detail-view.tsx"), "utf8"))
    expect(view).toContain("textState={view.textState}")
  })
})

describe("sessionTimeLabel and sessionRowView", () => {
  it("is the SPEC's shape: weekday, day, month, range, zone label", () => {
    expect(SESSION_ZONE_LABEL).toBe("Cairo time")
    expect(sessionTimeLabel(booking())).toBe("Thu 8 Jan · 17:00–18:00 Cairo time")
  })

  it("a row carries what S-36 lists: tutor, subject, time, mode and state", () => {
    const row = sessionRowView(booking({ mode: "in_person", effectiveState: "accepted" }))
    expect(row).toMatchObject({
      bookingId: "b1",
      tutorName: "Nour A.",
      subjectName: "Mathematics",
      timeLabel: "Thu 8 Jan · 17:00–18:00 Cairo time",
      modeLabel: "In person",
      state: "accepted",
    })
    expect(row.ariaLabel).toBe("Mathematics with Nour A., Thu 8 Jan · 17:00–18:00 Cairo time, Confirmed")
  })
})

describe("mergePages", () => {
  const key = (n: { id: string }) => n.id
  it("appends the next page in order and drops an item it already has", () => {
    const first = [{ id: "a" }, { id: "b" }]
    const next = [{ id: "b" }, { id: "c" }]
    expect(mergePages(first, next, key).map(key)).toEqual(["a", "b", "c"])
  })

  it("keeps the newer copy of a repeated item", () => {
    const merged = mergePages([{ id: "a", v: 1 }], [{ id: "a", v: 2 }], (n) => n.id)
    expect(merged).toEqual([{ id: "a", v: 2 }])
  })
})

// ── Errors ────────────────────────────────────────────────────────────────

describe("sessionActionError", () => {
  it("a cancel refused inside 24 hours reads the SPEC sentence, not the server's", () => {
    const text = sessionActionError(coded(409, "cancel_window_closed"), "cancel")
    expect(text).toBe(quotedAfter(S37, "Inside 24 h:").replace(" Message your tutor.", ""))
  })

  it("uses the typed copy for a code it knows and the action's fallback otherwise", () => {
    expect(sessionActionError(coded(409, "outcome_claim_not_open"), "complete")).toBe(
      "This session can't be marked as complete yet.",
    )
    expect(sessionActionError(new Error("socket hang up"), "cancel")).toBe(
      "We couldn't cancel this session. Try again.",
    )
    expect(sessionActionError(new Error("x"), "complete")).toBe("We couldn't mark this session completed. Try again.")
    expect(sessionActionError(new Error("x"), "review")).toBe("We couldn't save your review. Try again.")
  })

  it("is null when nothing failed, and never the raw error message", () => {
    expect(sessionActionError(null, "cancel")).toBeNull()
    expect(sessionActionError(undefined, "cancel")).toBeNull()
    expect(sessionActionError(new Error("secret internals"), "cancel")).not.toContain("secret")
  })

  it("a refused contact detail in a review uses the SPEC sentence", () => {
    expect(sessionActionError(coded(422, "contact_details_not_allowed"), "review")).toBe(
      "To keep everyone safe, keep contact details off Lemely. Use the session notes instead.",
    )
  })
})

// ── Source rules for the files this lane owns ─────────────────────────────

const OWNED_SOURCES = [
  "src/components/tutoring/session-detail-view.tsx",
  "src/components/tutoring/review-form.tsx",
  "src/components/tutoring/stop-sharing-sheet.tsx",
  "src/portals/student/screens/tutoring/Sessions.tsx",
  "src/portals/student/screens/tutoring/SessionDetail.tsx",
  "src/portals/student/screens/tutoring/TutorAccess.tsx",
  "src/lib/tutoring/sessionView.ts",
  "src/lib/tutoring/accessView.ts",
]

function source(file: string): string {
  return stripComments(readFileSync(join(WEB, file), "utf8"))
}

describe("what the owned files must not do", () => {
  it("scans eight files", () => {
    expect(OWNED_SOURCES).toHaveLength(8)
    for (const file of OWNED_SOURCES) expect(source(file).length, file).toBeGreaterThan(200)
  })

  it("never renders text as HTML or hands the browser a free-text URL", () => {
    for (const file of OWNED_SOURCES) {
      const code = source(file)
      expect(code, file).not.toMatch(/dangerouslySetInnerHTML|\.innerHTML|insertAdjacentHTML/)
      expect(code, file).not.toMatch(/window\.confirm|window\.alert|\balert\(/)
      expect(code, file).not.toMatch(/href=\{[^}]*(?:meetingLink|cancelReason|declineReason|locationDetail)/)
    }
  })

  it("every external link opens with noopener and noreferrer", () => {
    const view = source("src/components/tutoring/session-detail-view.tsx")
    const anchors = view.match(/<a\b[^>]*>/g) ?? []
    expect(anchors.length).toBeGreaterThanOrEqual(1)
    for (const anchor of anchors) expect(anchor).toContain('rel="noopener noreferrer"')
  })

  it("uses tokens and logical properties only", () => {
    for (const file of OWNED_SOURCES) {
      const code = source(file)
      expect(code, `${file}: arbitrary value`).not.toMatch(/\b[a-z-]+-\[[^\]]*\d[^\]]*\]/)
      expect(code, `${file}: hex colour`).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(code, `${file}: raw colour function`).not.toMatch(/\b(?:rgb|rgba|hsl|oklch)\(/)
      expect(code, file).not.toMatch(/\b(?:ml|mr|pl|pr)-\d/)
      expect(code, file).not.toMatch(/\b(?:left|right)-\d/)
      expect(code, file).not.toMatch(/\btext-(?:left|right)\b/)
      expect(code, file).not.toContain("rounded-full")
    }
  })

  it("the session view draws its controls from sessionActions, not from the state", () => {
    const view = source("src/components/tutoring/session-detail-view.tsx")
    expect(view).toContain("sessionActions(")
    // Not one read of allowedActions in the view itself: every control goes through
    // sessionActions. (The render tests in tutoringSessionScreens.test.ts prove what it draws.)
    expect(view).not.toContain("allowedActions")
  })
})
