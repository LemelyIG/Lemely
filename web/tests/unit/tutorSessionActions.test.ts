import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  ACCEPT_SERVICES,
  CANCEL_REASON_MAX,
  LATE_CANCEL_NOTICE,
  MEETING_HOSTS,
  TUTOR_ACTIONS,
  acceptBody,
  acceptDetailFor,
  cancelBody,
  cancelRequiresReason,
  declineBody,
  meetingLinkError,
  notesFreezeView,
  requestedByLabel,
  sessionQueuesView,
  sessionOutcomeLine,
  tutorActionFailureMessage,
  tutorLoadFailureMessage,
  tutorActions,
  validateAccept,
  validateCancelReason,
  lateCancelNeeded,
  reasonLength,
  shouldRefetchBooking,
} from "@/lib/tutoring/tutorSessionActions"
import { ApiError } from "@/lib/api"
import { CONTACT_DETAILS_MESSAGE } from "@/lib/tutoring/safetyNoticeCopy"
import type { ViewerAction } from "@/lib/tutoringTypes"

/*
 * T-18 (SPEC §d, §a.3, row 18): what the tutor can do with a session, and the
 * forms behind it.
 *
 * Expected sides come from the SPEC (the late-cancel sentence, the reason
 * limit, the action union) and from the Python module that owns the meeting
 * host allowlist, so the client mirror cannot drift from it unseen.
 */

const REPO = join(import.meta.dirname, "..", "..", "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")
const PATTERNS = readFileSync(join(REPO, "lemely", "core", "contact_patterns.py"), "utf8")
const BOOKING_REPO = readFileSync(join(REPO, "lemely", "db", "booking_repo.py"), "utf8")
const TYPES = readFileSync(join(REPO, "web", "src", "lib", "tutoringTypes.ts"), "utf8")

function pythonMeetingHosts(): string[] {
  const match = /MEETING_HOSTS: Final = \(([^)]*)\)/.exec(PATTERNS)
  expect(match).not.toBeNull()
  return [...(match?.[1] ?? "").matchAll(/"([a-z0-9.-]+)"/g)].map((m) => m[1])
}

function viewerActionUnion(): ViewerAction[] {
  const line = /export type ViewerAction = ([^\n]+)/.exec(TYPES)?.[1] ?? ""
  return [...line.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]) as ViewerAction[]
}

const ALL_ACTIONS = viewerActionUnion()

function subsets<T>(items: readonly T[]): T[][] {
  const out: T[][] = []
  for (let mask = 0; mask < 1 << items.length; mask++) {
    out.push(items.filter((_, i) => (mask & (1 << i)) !== 0))
  }
  return out
}

describe("actions come only from allowedActions", () => {
  it("reads the eight actions out of the shared type", () => {
    expect(ALL_ACTIONS).toHaveLength(8)
  })

  it("shows a control for an action only when the API allowed it, over every possible list", () => {
    const lists = subsets(ALL_ACTIONS)
    expect(lists).toHaveLength(256)
    for (const allowed of lists) {
      for (const shown of tutorActions(allowed)) {
        expect(allowed, `${shown} from ${allowed.join(",") || "nothing"}`).toContain(shown)
      }
    }
  })

  it("shows every tutor action the API allowed, and none that it did not", () => {
    for (const allowed of subsets(ALL_ACTIONS)) {
      const shown = new Set(tutorActions(allowed))
      for (const action of TUTOR_ACTIONS) {
        if (action === "cancel" || action === "cancel_with_reason") continue
        expect(shown.has(action), `${action} from ${allowed.join(",") || "nothing"}`).toBe(allowed.includes(action))
      }
    }
  })

  it("shows nothing for an empty list", () => {
    expect(tutorActions([])).toEqual([])
  })

  it("never turns a student action into a tutor control", () => {
    expect(tutorActions(["review", "post_note"])).toEqual([])
    expect(TUTOR_ACTIONS).not.toContain("review")
    expect(TUTOR_ACTIONS).not.toContain("post_note")
  })

  it("returns controls in a fixed order, whatever order the API listed them", () => {
    expect(tutorActions(["no_show", "complete"])).toEqual(["complete", "no_show"])
    expect(tutorActions(["decline", "accept"])).toEqual(["accept", "decline"])
  })

  it("offers one cancel at most, and the one that needs a reason wins if both arrive", () => {
    expect(tutorActions(["cancel"])).toEqual(["cancel"])
    expect(tutorActions(["cancel_with_reason"])).toEqual(["cancel_with_reason"])
    expect(tutorActions(["cancel", "cancel_with_reason"])).toEqual(["cancel_with_reason"])
  })

  it("knows when a cancel needs a reason", () => {
    expect(cancelRequiresReason(["cancel_with_reason"])).toBe(true)
    expect(cancelRequiresReason(["cancel"])).toBe(false)
    expect(cancelRequiresReason(["cancel", "cancel_with_reason"])).toBe(true)
    expect(cancelRequiresReason([])).toBe(false)
  })
})

describe("cancel_with_reason needs a non-blank reason before it can be sent", () => {
  it("words the late-cancel notice as the SPEC does", () => {
    const spec = /the sheet requires a reason: "([^"]+)"/.exec(SPEC)?.[1]
    expect(spec).toBeDefined()
    expect(LATE_CANCEL_NOTICE).toBe(spec)
  })

  it("refuses an empty or blank reason when one is required, and says what to do", () => {
    for (const reason of ["", " ", "   ", "\n\t "]) {
      const error = validateCancelReason(reason, true)
      expect(error, JSON.stringify(reason)).not.toBeNull()
      expect(error!.length).toBeGreaterThan(10)
    }
  })

  it("accepts a real reason", () => {
    expect(validateCancelReason("I am ill and cannot teach tomorrow.", true)).toBeNull()
    expect(validateCancelReason("  ill  ", true)).toBeNull()
  })

  it("holds the reason to the length the server enforces", () => {
    const serverMax = Number(/^MAX_REASON_LENGTH: Final = (\d+)/m.exec(BOOKING_REPO)?.[1])
    expect(serverMax).toBe(300)
    expect(CANCEL_REASON_MAX).toBe(serverMax)
    expect(validateCancelReason("x".repeat(serverMax), true)).toBeNull()
    expect(validateCancelReason("x".repeat(serverMax + 1), true)).not.toBeNull()
    expect(validateCancelReason("x".repeat(serverMax + 1), false)).not.toBeNull()
  })

  it("does not demand a reason for an ordinary cancel", () => {
    expect(validateCancelReason("", false)).toBeNull()
    expect(validateCancelReason("   ", false)).toBeNull()
  })

  it("sends the trimmed reason, and no reason at all when an ordinary cancel has none", () => {
    expect(cancelBody("  Ill today  ", true)).toEqual({ reason: "Ill today" })
    expect(cancelBody("   ", false)).toEqual({})
    expect(cancelBody("", false)).toEqual({})
    expect(cancelBody("Moving the day", false)).toEqual({ reason: "Moving the day" })
  })

  it("sends a decline with its optional reason", () => {
    expect(declineBody("  Not teaching that day ")).toEqual({ reason: "Not teaching that day" })
    expect(declineBody("  ")).toEqual({})
  })
})

describe("the meeting link must be https to an allowed service", () => {
  it("lists the same hosts as the server module", () => {
    const fromPython = pythonMeetingHosts()
    expect(fromPython).toHaveLength(5)
    expect([...MEETING_HOSTS].sort()).toEqual([...fromPython].sort())
  })

  it("names the four services in the SPEC", () => {
    const names = /allowed services listed: ([^)]+)\)/.exec(SPEC)?.[1] ?? ""
    for (const service of ACCEPT_SERVICES) expect(names).toContain(service)
    expect(ACCEPT_SERVICES).toHaveLength(4)
  })

  it("accepts https links on every allowed host and on their subdomains", () => {
    for (const host of pythonMeetingHosts()) {
      expect(meetingLinkError(`https://${host}/abc-defg-hij`), host).toBeNull()
      expect(meetingLinkError(`https://us02web.${host}/j/123456789`), `sub.${host}`).toBeNull()
    }
    expect(meetingLinkError("https://zoom.us:443/j/1")).toBeNull()
    expect(meetingLinkError("  https://meet.google.com/abc-defg-hij  ")).toBeNull()
  })

  it("refuses a link that is not https", () => {
    for (const link of ["http://meet.google.com/abc", "ftp://zoom.us/j/1", "javascript:alert(1)", "//meet.google.com/abc", "meet.google.com/abc"]) {
      expect(meetingLinkError(link), link).not.toBeNull()
    }
  })

  it("refuses look-alike hosts, userinfo, ports and addresses", () => {
    const bad = [
      "https://zoom.us.evil.example/j/1",
      "https://evilzoom.us/j/1",
      "https://zoom.us@evil.example/j/1",
      "https://user:pw@zoom.us/j/1",
      "https://zoom.us:8443/j/1",
      "https://zoom.us./j/1",
      "https://127.0.0.1/j/1",
      "https://[::1]/j/1",
      "https://example.com/zoom.us",
    ]
    for (const link of bad) expect(meetingLinkError(link), link).not.toBeNull()
  })

  it("refuses spaces, backslashes, control characters and non-ASCII text anywhere", () => {
    const bad = [
      "https://meet.google.com/a b",
      "https://meet.google.com\\@evil.example/",
      "https://meet.google.com/a\u0000b",
      "https://meet.google.com/a\tb",
      "https://meet.google.com/é",
      "https://mеet.google.com/abc",
    ]
    for (const link of bad) expect(meetingLinkError(link), JSON.stringify(link)).not.toBeNull()
  })

  it("refuses an empty link and one over the 500 characters the column holds", () => {
    expect(meetingLinkError("")).not.toBeNull()
    expect(meetingLinkError("   ")).not.toBeNull()
    expect(meetingLinkError(`https://meet.google.com/${"a".repeat(470)}`)).toBeNull()
    expect(meetingLinkError(`https://meet.google.com/${"a".repeat(500)}`)).not.toBeNull()
  })

  it("tells the tutor which services are allowed when it refuses", () => {
    const message = meetingLinkError("https://example.com/room") ?? ""
    expect(message).toMatch(/Google Meet/)
    expect(message).toMatch(/Zoom/)
  })
})

describe("the accept form asks only for the detail the mode keeps", () => {
  it("asks for a link for a virtual session, a place for in person, and nothing for other", () => {
    expect(acceptDetailFor("virtual")).toBe("link")
    expect(acceptDetailFor("in_person")).toBe("place")
    expect(acceptDetailFor("other")).toBe("none")
  })

  it("will not send a virtual accept without an allowed link", () => {
    expect(validateAccept("virtual", { meetingLink: "", locationDetail: "" }).meetingLink).toBeDefined()
    expect(validateAccept("virtual", { meetingLink: "http://zoom.us/j/1", locationDetail: "" }).meetingLink).toBeDefined()
    expect(validateAccept("virtual", { meetingLink: "https://zoom.us/j/1", locationDetail: "" })).toEqual({})
  })

  it("will not send an in-person accept without a place, and holds it to 300 characters", () => {
    expect(validateAccept("in_person", { meetingLink: "", locationDetail: "  " }).locationDetail).toBeDefined()
    expect(validateAccept("in_person", { meetingLink: "", locationDetail: "x".repeat(301) }).locationDetail).toBeDefined()
    expect(validateAccept("in_person", { meetingLink: "", locationDetail: "Cafe on Road 9, upstairs" })).toEqual({})
  })

  it("accepts an 'other' session with nothing", () => {
    expect(validateAccept("other", { meetingLink: "", locationDetail: "" })).toEqual({})
  })

  it("sends only the kept detail, trimmed, and drops the other", () => {
    const values = { meetingLink: " https://zoom.us/j/1 ", locationDetail: " Road 9 " }
    expect(acceptBody("virtual", values)).toEqual({ meetingLink: "https://zoom.us/j/1" })
    expect(acceptBody("in_person", values)).toEqual({ locationDetail: "Road 9" })
    expect(acceptBody("other", values)).toEqual({})
  })
})

describe("what the tutor is told about who asked, and about frozen notes", () => {
  it("always says the student, so a tutor never learns a parent link exists", () => {
    expect(requestedByLabel("student")).toBe("the student")
    expect(requestedByLabel("parent")).toBe("the student")
    expect(requestedByLabel("parent").toLowerCase()).not.toContain("parent")
  })

  it("treats a freeze as a report's unless the tutor's own block explains it", () => {
    const view = (notesFrozen: boolean, studentId: string, blocked: string[] | null) =>
      notesFreezeView({ notesFrozen, studentId, blockedStudentIds: blocked })
    expect(view(false, "s1", ["s1"])).toEqual({ frozen: false, ownBlock: false })
    expect(view(true, "s1", ["s2"])).toEqual({ frozen: true, ownBlock: false })
    expect(view(true, "s1", ["s1", "s2"])).toEqual({ frozen: false, ownBlock: true })
  })

  it("falls back to the plain freeze line when the block list could not be read", () => {
    expect(notesFreezeView({ notesFrozen: true, studentId: "s1", blockedStudentIds: null })).toEqual({
      frozen: true,
      ownBlock: false,
    })
  })
})

describe("failure sentences", () => {
  const refusal = (status: number, code: string) => new ApiError(status, "x", { code, message: "server words" })

  it("uses the API's own sentence for a refusal it sent on purpose, never the server's raw message", () => {
    const message = tutorActionFailureMessage(refusal(409, "illegal_transition"), "fallback")
    expect(message).toBe("This booking has already moved on, so that is no longer possible.")
    expect(message).not.toContain("server words")
  })

  it("uses the SPEC contact-details sentence for a refused contact detail", () => {
    expect(tutorActionFailureMessage(refusal(422, "contact_details_not_allowed"), "fallback")).toBe(
      CONTACT_DETAILS_MESSAGE,
    )
  })

  it("falls back for anything else, and says nothing when nothing failed", () => {
    expect(tutorActionFailureMessage(new Error("boom"), "We couldn't cancel.")).toBe("We couldn't cancel.")
    expect(tutorActionFailureMessage(null, "x")).toBeNull()
    expect(tutorActionFailureMessage(undefined, "x")).toBeNull()
  })

  it("words a load failure with the refusal's sentence or the shared one", () => {
    expect(tutorLoadFailureMessage(refusal(404, "not_found"))).toBe("We couldn't find that.")
    expect(tutorLoadFailureMessage(new Error("boom")).length).toBeGreaterThan(10)
  })
})

describe("how a session ended, as the tutor reads it", () => {
  const base = {
    cancelledBy: null,
    cancelledLate: false,
    cancelReason: null,
    declineReason: null,
    completedBy: null,
  } as const

  it("says nothing while the session is live", () => {
    expect(sessionOutcomeLine({ ...base, effectiveState: "requested" })).toBeNull()
    expect(sessionOutcomeLine({ ...base, effectiveState: "accepted" })).toBeNull()
  })

  it("quotes the tutor's own reasons as plain text", () => {
    expect(sessionOutcomeLine({ ...base, effectiveState: "declined", declineReason: "Fully booked" })).toContain("Fully booked")
    const late = sessionOutcomeLine({
      ...base,
      effectiveState: "cancelled",
      cancelledBy: "tutor",
      cancelledLate: true,
      cancelReason: "<b>Ill</b>",
    })
    expect(late).toContain("less than 24 hours")
    expect(late).toContain("<b>Ill</b>")
  })

  it("never mentions a parent, whoever cancelled or completed", () => {
    const lines = [
      sessionOutcomeLine({ ...base, effectiveState: "cancelled", cancelledBy: "parent" }),
      sessionOutcomeLine({ ...base, effectiveState: "completed", completedBy: "parent" }),
      sessionOutcomeLine({ ...base, effectiveState: "cancelled", cancelledBy: "system" }),
    ]
    for (const line of lines) expect(line?.toLowerCase()).not.toContain("parent")
  })

  it("reads a system cancellation and an admin cancellation the same, so a block cannot be told apart", () => {
    const system = sessionOutcomeLine({ ...base, effectiveState: "cancelled", cancelledBy: "system" })
    const admin = sessionOutcomeLine({ ...base, effectiveState: "cancelled", cancelledBy: "platform_admin" })
    expect(system).toBe(admin)
    expect(system).not.toBeNull()
  })

  it("has a sentence for every state that has ended", () => {
    for (const state of ["declined", "expired", "cancelled", "completed", "no_show", "awaiting_outcome"] as const) {
      expect(sessionOutcomeLine({ ...base, effectiveState: state })?.length, state).toBeGreaterThan(10)
    }
  })
})

describe("which sessions the tutoring home draws for each listing state", () => {
  const states = ["draft", "pending_review", "listed", "rejected", "suspended", "closed"] as const

  it("draws the queues for every state a profile can have bookings in", () => {
    // A rejected, suspended or closed profile can still hold requests, accepted
    // sessions and sessions awaiting an outcome (SPEC §a.3: rejection cancels nothing).
    for (const state of ["pending_review", "listed", "rejected", "suspended", "closed"] as const) {
      expect(sessionQueuesView(state).show, state).toBe(true)
    }
  })

  it("draws no queues for a draft, which has never been listed", () => {
    expect(sessionQueuesView("draft")).toEqual({
      show: false,
      note: "Requests and sessions will appear here once your profile is listed.",
    })
  })

  it("explains a suspended or closed profile and says nothing for the others", () => {
    expect(sessionQueuesView("suspended").note).toContain("suspended")
    expect(sessionQueuesView("closed").note).toContain("closed")
    for (const state of states.filter((s) => !["draft", "suspended", "closed"].includes(s))) {
      expect(sessionQueuesView(state).note, state).toBeNull()
    }
  })

  it("covers every listing state in the SPEC", () => {
    const spec = /\| `tutorlistingstate` \| ([^|]*)\|/.exec(SPEC)
    const named = [...(spec?.[1] ?? "").matchAll(/`([a-z_]+)`/g)].map((m) => m[1])
    expect(named.sort()).toEqual([...states].sort())
  })
})

describe("a refusal that means the session page is out of date", () => {
  it("reads 422 reason_required as the late-cancel case", () => {
    expect(lateCancelNeeded(new ApiError(422, "x", { code: "reason_required", message: "m" }))).toBe(true)
    expect(lateCancelNeeded(new ApiError(422, "x", { code: "contact_details_not_allowed" }))).toBe(false)
    expect(lateCancelNeeded(new ApiError(409, "x", { code: "illegal_transition" }))).toBe(false)
    expect(lateCancelNeeded(new Error("network"))).toBe(false)
  })

  it("refetches the booking after a 409 or 422, and not after other failures", () => {
    expect(shouldRefetchBooking(new ApiError(409, "x", { code: "illegal_transition" }))).toBe(true)
    expect(shouldRefetchBooking(new ApiError(422, "x", { code: "reason_required" }))).toBe(true)
    expect(shouldRefetchBooking(new ApiError(500, "x", null))).toBe(false)
    expect(shouldRefetchBooking(new ApiError(429, "x", null))).toBe(false)
    expect(shouldRefetchBooking(new Error("network"))).toBe(false)
  })
})

describe("reason limits count code points, as validateCancelReason does", () => {
  it("counts a character outside the BMP once", () => {
    expect(reasonLength("a\u{1F600}b")).toBe(3)
    expect(reasonLength("")).toBe(0)
    const emoji = "\u{1F600}".repeat(CANCEL_REASON_MAX)
    expect(validateCancelReason(emoji, true)).toBeNull()
    expect(reasonLength(emoji)).toBe(CANCEL_REASON_MAX)
  })
})
