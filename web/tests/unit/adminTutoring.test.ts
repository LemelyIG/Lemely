import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement as h, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { Moderation } from "@/portals/admin/screens/tutoring/Moderation"
import { ReportDetail as ReportDetailScreen } from "@/portals/admin/screens/tutoring/ReportDetail"
import { Reports } from "@/portals/admin/screens/tutoring/Reports"
import { DecisionDialog, TutorApplication } from "@/portals/admin/screens/tutoring/TutorApplication"
import { TutorQueue } from "@/portals/admin/screens/tutoring/TutorQueue"
import { TUTORING_ERROR_COPY } from "@/lib/tutoring/apiErrors"
import {
  CLOSE_CONFIRM,
  DECISION_COPY,
  DECISION_NOTE_MAX,
  EVIDENCE_LINK_TTL_SECONDS,
  MOCK_EMAIL_TITLE,
  QUEUE_STATES,
  RESOLUTION_NOTE_MAX,
  SUSPEND_CONSEQUENCE,
  THREAD_VIEW_NOTICE,
  adminFailureMessage,
  adminNoteRows,
  approveBody,
  approveDoneLine,
  approveGate,
  availableDecisions,
  cancelWindowMs,
  completedByLabel,
  decisionBody,
  decisionLabel,
  decisionNoteError,
  decisionNoteRule,
  emailDeliveryNotice,
  evidenceLinkSecondsLeft,
  evidenceLinksExpired,
  formatAdminInstant,
  formatAdminRange,
  formatFileSize,
  isAlreadyResolved,
  isSafetyConcern,
  listingStateLabel,
  moderationDoneLine,
  moderationRequest,
  noteError,
  noteLabel,
  noteLength,
  noteValue,
  queueEmpty,
  reporterLabel,
  reportReasonLabel,
  resolveReadiness,
  resolutionStillOffered,
  threadNotes,
  reportTargetLabel,
  resolutionConfirm,
  resolutionNoteError,
  resolutionOptions,
  resolutionUnavailable,
  resolveBody,
  snapshotRows,
  type EvidenceLink,
} from "@/lib/tutoring/adminTutoring"
import type {
  AdminBookingSummary,
  AdminTutorDetail,
  EffectiveState,
  ModerationItem,
  Note,
  ReportDetail,
  ReportResolution,
} from "@/lib/tutoringTypes"

// ── Screen wiring: what the five screens do with these rules ────────────────
//
// The web runner is `environment: "node"` with no jsdom (D3.20), so the screens
// render to static markup with `react-dom/server`. Four things are replaced,
// none of them the code under test: the API hooks (they answer from `hooks`),
// `Modal` (the real one is a portal into `document.body`), `Button` (so a click
// can be made by calling the handler the screen gave it) and the online flag.

const hooks = vi.hoisted(() => {
  const idle = () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, error: null as unknown })
  return {
    tutors: null as unknown,
    tutor: null as unknown,
    moderation: null as unknown,
    reports: null as unknown,
    report: null as unknown,
    idle,
    review: idle(),
    reply: idle(),
    approve: idle(),
    resolve: idle(),
    forms: [] as Array<Record<string, unknown>>,
    clicks: [] as Array<{ label: string; onClick: (() => void) | undefined; disabled: boolean }>,
  }
})

vi.mock("@/lib/hooks/useTutoringApi", () => ({
  useAdminTutors: () => hooks.tutors,
  useAdminTutor: () => hooks.tutor,
  useApproveTutor: () => hooks.approve,
  useRejectTutor: () => hooks.idle(),
  useSuspendTutor: () => hooks.idle(),
  useCloseTutor: () => hooks.idle(),
  useAdminModeration: () => hooks.moderation,
  useModerateReview: () => hooks.review,
  useModerateReply: () => hooks.reply,
  useAdminTutoringReports: () => hooks.reports,
  useAdminTutoringReport: () => hooks.report,
  useResolveTutoringReport: () => hooks.resolve,
}))

vi.mock("@/components/ui/modal", () => ({
  Modal: (props: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    props.open
      ? h("div", { role: "dialog" }, h("h2", null, props.title as never), props.children as never, props.footer as never)
      : null,
}))

vi.mock("@/components/ui/button", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/components/ui/button")>()
  return {
    ...original,
    Button: (props: Record<string, unknown>) => {
      hooks.clicks.push({
        label: String(props["aria-label"] ?? (typeof props.children === "string" ? props.children : "")),
        onClick: props.onClick as (() => void) | undefined,
        disabled: Boolean(props.disabled),
      })
      return h(
        "button",
        { type: (props.type as string | undefined) ?? "button", disabled: Boolean(props.disabled), "aria-label": props["aria-label"] },
        props.children as never,
      )
    },
  }
})

// A submit cannot be fired in a node renderer, so the props of every <form> the
// screens create are kept and the test calls the `onSubmit` the screen gave.
vi.mock("react/jsx-dev-runtime", async (importOriginal) => {
  const original = await importOriginal<typeof import("react/jsx-dev-runtime")>()
  return {
    ...original,
    jsxDEV: (type: unknown, props: Record<string, unknown>, ...rest: unknown[]) => {
      if (type === "form") hooks.forms.push(props)
      return (original.jsxDEV as (...args: unknown[]) => unknown)(type, props, ...rest)
    },
  }
})
vi.mock("react/jsx-runtime", async (importOriginal) => {
  const original = await importOriginal<typeof import("react/jsx-runtime")>()
  const wrap = (make: (...args: unknown[]) => unknown) => (type: unknown, props: Record<string, unknown>, ...rest: unknown[]) => {
    if (type === "form") hooks.forms.push(props)
    return make(type, props, ...rest)
  }
  return { ...original, jsx: wrap(original.jsx as never), jsxs: wrap(original.jsxs as never) }
})

vi.mock("@/lib/online", () => ({ useOnlineStatus: () => true, isOnline: () => true }))

/*
 * T28 · the platform-admin tutoring screens X-04..X-07 (SPEC §d, rows A1-A12):
 * what the screens decide, apart from how they look.
 *
 * Expected sides come from outside this lane's own code wherever they can: the
 * note limit from `tutor_approval_repo.MAX_NOTE_LENGTH`, the resolution note
 * limit from the report table's CHECK in SPEC §a.2, the close sentence, the
 * "Email delivery: mock" banner and the evidence link lifetime from SPEC text.
 * Each is parsed, not retyped.
 */

const REPO = join(import.meta.dirname, "..", "..", "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")
const APPROVAL_REPO = readFileSync(join(REPO, "lemely", "db", "tutor_approval_repo.py"), "utf8")

const X05 = SPEC.slice(SPEC.indexOf("**X-05 "), SPEC.indexOf("**X-06 "))
const X04 = SPEC.slice(SPEC.indexOf("**X-04 "), SPEC.indexOf("**X-05 "))
const A11 = SPEC.split("\n").find((line) => line.startsWith("| A11 |")) ?? ""

function specQuoted(block: string, anchor: string): string {
  const at = block.indexOf(anchor)
  expect(at, `anchor not in SPEC: ${anchor}`).toBeGreaterThan(-1)
  const open = block.indexOf('"', at + anchor.length)
  return block.slice(open + 1, block.indexOf('"', open + 1))
}

function pythonConstant(source: string, name: string): number {
  const match = new RegExp(`${name}: Final = (\\d+)`).exec(source)
  expect(match, `${name} not in the Python source`).not.toBeNull()
  return Number(match![1])
}

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date("2026-10-30T12:00:00Z")
const HOUR = 3_600_000

/** `base` is the clock the booking is placed against: the fixed NOW, or the real clock for a screen that reads its own. */
function summary(effectiveState: EffectiveState, startOffsetHours: number, base: number = NOW.getTime()): AdminBookingSummary {
  const starts = new Date(base + startOffsetHours * HOUR)
  return {
    bookingId: "b1",
    subject: { code: "0580", name: "Mathematics" },
    mode: "virtual",
    startsAt: starts.toISOString(),
    endsAt: new Date(starts.getTime() + HOUR).toISOString(),
    effectiveState,
    completedBy: null,
    notesFrozen: true,
    declineReason: null,
    cancelReason: null,
    locationDetail: null,
    otherModeNote: null,
  }
}

function report(
  targetType: ReportDetail["targetType"],
  bookingSummary: AdminBookingSummary | null,
  overrides: Partial<ReportDetail> = {},
): ReportDetail {
  return {
    reportId: "r1",
    targetType,
    reason: "other",
    state: "open",
    createdAt: "2026-10-29T09:00:00Z",
    reporterParty: "student",
    details: null,
    tutorId: "t1",
    tutorName: "Dina A.",
    tutorListingState: "listed",
    snapshot: {},
    bookingSummary,
    notes: [],
    resolution: null,
    resolutionNote: null,
    resolvedAt: null,
    ...overrides,
  }
}

function values(options: { value: ReportResolution }[]): ReportResolution[] {
  return options.map((option) => option.value)
}

const FILE_A: EvidenceLink = { evidenceId: "e1", signedUrl: "https://files.example/e1" }
const FILE_B: EvidenceLink = { evidenceId: "e2", signedUrl: "https://files.example/e2" }

// ── Notes ───────────────────────────────────────────────────────────────────

describe("notes: required, non-blank, at most the server limit in code points", () => {
  it("takes the decision note limit from the Python constant the server checks", () => {
    expect(DECISION_NOTE_MAX).toBe(pythonConstant(APPROVAL_REPO, "MAX_NOTE_LENGTH"))
    expect(DECISION_NOTE_MAX).toBe(2000)
  })

  it("takes the resolution note limit from the report table's CHECK", () => {
    const match = /char_length\(resolution_note\) <= (\d+)/.exec(SPEC)
    expect(match).not.toBeNull()
    expect(RESOLUTION_NOTE_MAX).toBe(Number(match![1]))
  })

  it("counts code points, not UTF-16 units", () => {
    expect(noteLength("abc")).toBe(3)
    expect(noteLength("😀".repeat(5))).toBe(5)
    expect("😀".repeat(5).length).toBe(10)
  })

  it("refuses a missing or blank required note and accepts any other", () => {
    const rule = { required: true, max: 2000 }
    expect(noteError("", rule)).not.toBeNull()
    expect(noteError("   \n\t ", rule)).not.toBeNull()
    expect(noteError("Photo ID is unreadable.", rule)).toBeNull()
    expect(noteError("", { required: false, max: 2000 })).toBeNull()
  })

  it("accepts exactly the limit and refuses one past it, counting emoji once", () => {
    const rule = { required: true, max: DECISION_NOTE_MAX }
    expect(noteError("a".repeat(DECISION_NOTE_MAX), rule)).toBeNull()
    expect(noteError("a".repeat(DECISION_NOTE_MAX + 1), rule)).not.toBeNull()
    expect(noteError("😀".repeat(DECISION_NOTE_MAX), rule)).toBeNull()
    expect(noteError("😀".repeat(DECISION_NOTE_MAX + 1), rule)).not.toBeNull()
  })

  it("measures the trimmed note, as it will be sent", () => {
    const rule = { required: true, max: 10 }
    expect(noteError(`  ${"a".repeat(10)}  `, rule)).toBeNull()
  })

  it("sends a trimmed note or null", () => {
    expect(noteValue("  hello  ")).toBe("hello")
    expect(noteValue("   ")).toBeNull()
    expect(noteValue("")).toBeNull()
  })
})

// ── X-05 decisions ──────────────────────────────────────────────────────────

describe("X-05 decisions: reject and suspend need a note", () => {
  it("requires a note for reject and suspend, and only those", () => {
    expect(decisionNoteRule("reject").required).toBe(true)
    expect(decisionNoteRule("suspend").required).toBe(true)
    expect(decisionNoteRule("approve").required).toBe(false)
    expect(decisionNoteRule("close").required).toBe(false)
  })

  it("refuses a blank or over-long note for reject and suspend", () => {
    for (const decision of ["reject", "suspend"] as const) {
      expect(decisionNoteError(decision, "")).not.toBeNull()
      expect(decisionNoteError(decision, "  ")).not.toBeNull()
      expect(decisionNoteError(decision, "x".repeat(DECISION_NOTE_MAX + 1))).not.toBeNull()
      expect(decisionNoteError(decision, "Needs a clearer document.")).toBeNull()
    }
  })

  it("lets approve and close go without a note, but not with an over-long one", () => {
    for (const decision of ["approve", "close"] as const) {
      expect(decisionNoteError(decision, "")).toBeNull()
      expect(decisionNoteError(decision, "x".repeat(DECISION_NOTE_MAX + 1))).not.toBeNull()
    }
  })

  it("builds the A4/A5/A12 body from the trimmed note", () => {
    expect(decisionBody("reject", "  Blurry scan.  ")).toEqual({ note: "Blurry scan." })
    expect(decisionBody("close", "")).toEqual({ note: null })
  })

  it("offers each listing state only the decisions SPEC §a.3 allows", () => {
    expect(availableDecisions("pending_review")).toEqual(["approve", "reject", "suspend", "close"])
    expect(availableDecisions("listed")).toEqual(["suspend", "close"])
    expect(availableDecisions("rejected")).toEqual(["suspend", "close"])
    expect(availableDecisions("suspended")).toEqual(["approve", "close"])
    expect(availableDecisions("draft")).toEqual(["close"])
    expect(availableDecisions("closed")).toEqual([])
  })

  it("calls approve on a suspended profile Reinstate", () => {
    expect(decisionLabel("approve", "pending_review")).toBe("Approve")
    expect(decisionLabel("approve", "suspended")).toBe("Reinstate")
    expect(decisionLabel("suspend", "listed")).toBe("Suspend")
    expect(decisionLabel("close", "listed")).toBe("Close")
    expect(decisionLabel("reject", "pending_review")).toBe("Reject")
  })

  it("uses the SPEC's close sentence, word for word", () => {
    expect(CLOSE_CONFIRM).toBe(specQuoted(X05, "(confirm:"))
  })

  it("says what a suspension does before it is confirmed", () => {
    expect(SUSPEND_CONSEQUENCE).toMatch(/future sessions/)
    expect(SUSPEND_CONSEQUENCE).toMatch(/sharing/)
    expect(SUSPEND_CONSEQUENCE).toMatch(/Reinstating/)
  })

  it("says that closing removes students from the tutor's classes outside a school, after the SPEC sentence", () => {
    const { consequence } = DECISION_COPY.close
    expect(consequence.startsWith(CLOSE_CONFIRM)).toBe(true)
    expect(consequence).toContain("It also removes students from the classes this tutor teaches outside a school.")
  })

  it("says that suspending removes the students who booked or shared, from those classes", () => {
    expect(SUSPEND_CONSEQUENCE).toMatch(/It also removes students who have booked or shared with this tutor from the classes this tutor teaches outside a school\./)
    expect(DECISION_COPY.suspend.consequence).toBe(SUSPEND_CONSEQUENCE)
    expect(resolutionConfirm("tutor_suspended")?.body).toBe(SUSPEND_CONSEQUENCE)
  })
})

// ── X-05 approve gate ───────────────────────────────────────────────────────

describe("X-05 Approve: disabled until the documents box is ticked and every file was opened", () => {
  const opened = (...ids: string[]) => new Set(ids)

  it("is disabled when the box is not ticked, even with every file opened", () => {
    const gate = approveGate({ documentsSeen: false, evidence: [FILE_A, FILE_B], opened: opened("e1", "e2") })
    expect(gate.enabled).toBe(false)
    expect(gate.reason).toMatch(/I looked at the documents/)
  })

  it("is disabled when the box is ticked and a file was not opened", () => {
    const gate = approveGate({ documentsSeen: true, evidence: [FILE_A, FILE_B], opened: opened("e1") })
    expect(gate.enabled).toBe(false)
    expect(gate.unopened).toBe(1)
    expect(gate.reason).toMatch(/1 file/)
  })

  it("is enabled when the box is ticked and every file was opened", () => {
    const gate = approveGate({ documentsSeen: true, evidence: [FILE_A, FILE_B], opened: opened("e1", "e2") })
    expect(gate).toEqual({ enabled: true, reason: null, unopened: 0 })
  })

  it("needs only the box when the tutor uploaded no files", () => {
    expect(approveGate({ documentsSeen: true, evidence: [], opened: opened() }).enabled).toBe(true)
    expect(approveGate({ documentsSeen: false, evidence: [], opened: opened() }).enabled).toBe(false)
  })

  it("does not count a file that has no link as opened", () => {
    const noLink: EvidenceLink = { evidenceId: "e3", signedUrl: null }
    const gate = approveGate({ documentsSeen: true, evidence: [FILE_A, noLink], opened: opened("e1", "e3") })
    expect(gate.enabled).toBe(false)
    expect(gate.reason).toMatch(/reload/i)
  })

  it("ignores an opened id that is no longer one of the files", () => {
    const gate = approveGate({ documentsSeen: true, evidence: [FILE_A], opened: opened("gone") })
    expect(gate.enabled).toBe(false)
    expect(gate.unopened).toBe(1)
  })

  it("never builds an approval that claims documentsSeen while the gate is shut", () => {
    const shut = { documentsSeen: true, evidence: [FILE_A], opened: opened() }
    expect(approveBody(shut, "ok")).toBeNull()
    const open = { documentsSeen: true, evidence: [FILE_A], opened: opened("e1") }
    expect(approveBody(open, "  Documents match the profile.  ")).toEqual({
      documentsSeen: true,
      note: "Documents match the profile.",
    })
    expect(approveBody(open, "")).toEqual({ documentsSeen: true, note: null })
  })
})

describe("X-05 evidence links: 300 second downloads", () => {
  it("takes the lifetime from SPEC §b.3", () => {
    const match = /tutor_evidence_signed_url_ttl_seconds = (\d+)/.exec(SPEC)
    expect(match).not.toBeNull()
    expect(EVIDENCE_LINK_TTL_SECONDS).toBe(Number(match![1]))
  })

  it("expires exactly when the lifetime is up", () => {
    expect(evidenceLinksExpired(0, 299_000)).toBe(false)
    expect(evidenceLinkSecondsLeft(0, 299_000)).toBe(1)
    expect(evidenceLinksExpired(0, 300_000)).toBe(true)
    expect(evidenceLinkSecondsLeft(0, 900_000)).toBe(0)
  })

  it("formats a file size in plain units", () => {
    expect(formatFileSize(512)).toBe("512 B")
    expect(formatFileSize(2048)).toBe("2 KB")
    expect(formatFileSize(1_572_864)).toBe("1.5 MB")
  })
})

describe("X-05 sentences", () => {
  it("tells the tutor to read the note, only where the tutor does", () => {
    expect(DECISION_COPY.reject.noteHint).toMatch(/tutor reads/)
    expect(DECISION_COPY.suspend.noteHint).toMatch(/tutor sees/)
    expect(DECISION_COPY.close.noteLabel).toMatch(/optional/)
  })

  it("says whether a reinstatement listed the tutor or sent the profile back to review", () => {
    expect(approveDoneLine("pending_review", "listed")).toBe("Approved. The tutor is listed.")
    expect(approveDoneLine("suspended", "listed")).toBe("Reinstated. The tutor is listed.")
    expect(approveDoneLine("suspended", "pending_review")).toBe("Reinstated. The profile is back in review.")
  })

  it("does not word a tutor's stale decision as a booking", () => {
    const stale = new ApiError(409, "x", { code: "illegal_transition", message: "x" })
    expect(adminFailureMessage(stale, "f")).not.toMatch(/booking/i)
    expect(adminFailureMessage(stale, "f")).toMatch(/Reload/)
  })

  it("names every listing state and an empty queue for each", () => {
    expect(listingStateLabel("pending_review")).toBe("Waiting for review")
    expect(queueEmpty("pending_review").heading).toBe("No applications waiting")
    expect(queueEmpty("suspended").heading).toBe("No suspended tutors")
  })

  it("formats a booking range in one zone with both times", () => {
    const text = formatAdminRange("2026-10-30T15:00:00Z", "2026-10-30T16:00:00Z", "Africa/Cairo")
    expect(text).toMatch(/17:00–18:00/)
  })
})

// ── X-04 ────────────────────────────────────────────────────────────────────

describe("X-04: the email banner appears only for the mock", () => {
  it("uses the SPEC's banner title", () => {
    expect(MOCK_EMAIL_TITLE).toBe(specQuoted(X04, "state filter)"))
  })

  it("shows it for mock", () => {
    const notice = emailDeliveryNotice("mock")
    expect(notice).not.toBeNull()
    expect(notice?.title).toBe(MOCK_EMAIL_TITLE)
    expect(notice?.body.length).toBeGreaterThan(20)
  })

  it("shows nothing for a real provider, an unknown value or while loading", () => {
    expect(emailDeliveryNotice("provider")).toBeNull()
    expect(emailDeliveryNotice(undefined)).toBeNull()
    expect(emailDeliveryNotice("sendgrid" as never)).toBeNull()
  })

  it("filters by the listing states a queue can hold, waiting for review first", () => {
    expect(QUEUE_STATES.map((state) => state.value)).toEqual([
      "pending_review",
      "listed",
      "suspended",
      "rejected",
      "closed",
    ])
  })
})

// ── X-06 ────────────────────────────────────────────────────────────────────

describe("X-06 moderation: a review decision echoes the revision it was shown", () => {
  const review: ModerationItem = {
    kind: "review",
    itemId: "rev1",
    text: "Great tutor.",
    createdAt: "2026-10-29T09:00:00Z",
    revision: "0123456789abcdef",
  }
  const reply: ModerationItem = { ...review, kind: "reply", itemId: "rep1", revision: "fedcba9876543210" }

  it("sends the revision with approve and with reject on a review", () => {
    expect(moderationRequest(review, "approved")).toEqual({
      kind: "review",
      id: "rev1",
      body: { decision: "approved", revision: "0123456789abcdef" },
    })
    expect(moderationRequest(review, "rejected").body).toEqual({
      decision: "rejected",
      revision: "0123456789abcdef",
    })
  })

  it("sends a reply decision alone, because a reply cannot be edited", () => {
    const request = moderationRequest(reply, "approved")
    expect(request).toEqual({ kind: "reply", id: "rep1", body: { decision: "approved" } })
    expect(Object.keys(request.body)).toEqual(["decision"])
  })

  it("explains a text that changed in the API's own words and says to reload", () => {
    const changed = new ApiError(409, "Conflict", { code: "text_changed", message: "x" })
    expect(adminFailureMessage(changed, "fallback")).toBe(TUTORING_ERROR_COPY.text_changed)
  })

  it("names what was decided", () => {
    expect(moderationDoneLine("review", "approved")).toBe("Review text approved.")
    expect(moderationDoneLine("reply", "rejected")).toBe("Reply rejected.")
  })
})

describe("admin failures: the API's code picks the sentence", () => {
  const refusal = (status: number, code: string) => new ApiError(status, "x", { code, message: "x" })

  it("covers the codes the admin routes send that the shared list does not carry yet", () => {
    expect(adminFailureMessage(refusal(422, "note_required"), "f")).toMatch(/note/i)
    // A4/A5/A12 allow 2000 and A11 allows 1000, so the sentence names no number.
    const tooLong = adminFailureMessage(refusal(422, "note_too_long"), "f")
    expect(tooLong).toBe("That note is too long. Shorten it and try again.")
    expect(tooLong).not.toMatch(/\d/)
    expect(adminFailureMessage(refusal(409, "documents_not_opened"), "f")).toMatch(/open/i)
  })

  it("uses the shared sentence for a code it does carry", () => {
    expect(adminFailureMessage(refusal(409, "already_resolved"), "f")).toBe(TUTORING_ERROR_COPY.already_resolved)
    expect(adminFailureMessage(refusal(409, "resolution_not_applicable"), "f")).toBe(
      TUTORING_ERROR_COPY.resolution_not_applicable,
    )
    expect(adminFailureMessage(refusal(409, "already_closed"), "f")).toBe(TUTORING_ERROR_COPY.already_closed)
  })

  it("falls back for anything else and never repeats a machine's words", () => {
    expect(adminFailureMessage(new Error("boom"), "Could not save.")).toBe("Could not save.")
    expect(adminFailureMessage(new ApiError(500, "Traceback"), "Could not save.")).toBe("Could not save.")
    expect(adminFailureMessage(null, "Could not save.")).toBe("Could not save.")
  })
})

// ── X-07 ────────────────────────────────────────────────────────────────────

describe("X-07 resolutions: limited by what A11 can apply", () => {
  it("states the two booking rules in the SPEC's A11 row", () => {
    // The server is stricter on booking_completed (a disputed-outcome report on the booking itself, SPEC §a.3).
    expect(A11).toContain("`booking_cancelled` after `starts_at`")
    expect(A11).toContain("`booking_completed` unless the target booking is `awaiting_outcome` or `no_show`")
  })

  it("excludes booking_cancelled for a booking target after it started", () => {
    const started = report("booking", summary("awaiting_outcome", -3))
    expect(values(resolutionOptions(started, NOW))).not.toContain("booking_cancelled")
    const inProgress = report("booking", summary("accepted", -0.5))
    expect(values(resolutionOptions(inProgress, NOW))).not.toContain("booking_cancelled")
  })

  it("offers booking_cancelled for an accepted booking that has not started", () => {
    const upcoming = report("booking", summary("accepted", 5))
    expect(values(resolutionOptions(upcoming, NOW))).toContain("booking_cancelled")
  })

  it("offers booking_cancelled for a request that has not started, as the server accepts", () => {
    expect(values(resolutionOptions(report("booking", summary("requested", 5)), NOW))).toContain("booking_cancelled")
  })

  it("does not offer booking_cancelled for a booking that is no longer active", () => {
    for (const state of ["declined", "cancelled", "completed", "expired"] as const) {
      const options = values(resolutionOptions(report("booking", summary(state, 5)), NOW))
      expect(options, state).not.toContain("booking_cancelled")
    }
  })

  const disputed = { reason: "disputed_outcome" } as const

  it("offers booking_completed only for awaiting_outcome and no_show", () => {
    for (const state of ["awaiting_outcome", "no_show"] as const) {
      expect(values(resolutionOptions(report("booking", summary(state, -3), disputed), NOW)), state).toContain(
        "booking_completed",
      )
    }
    for (const state of ["requested", "accepted", "declined", "cancelled", "completed", "expired"] as const) {
      expect(values(resolutionOptions(report("booking", summary(state, 5), disputed), NOW)), state).not.toContain(
        "booking_completed",
      )
    }
  })

  it("offers booking_completed only on a disputed-outcome report about the booking itself", () => {
    const ended = summary("awaiting_outcome", -3)
    expect(values(resolutionOptions(report("booking", ended, { reason: "harassment" }), NOW))).not.toContain("booking_completed")
    expect(values(resolutionOptions(report("booking_note", ended, disputed), NOW))).not.toContain("booking_completed")
  })

  it("applies the booking rules to a note report through its booking", () => {
    const note = report("booking_note", summary("accepted", 5))
    expect(values(resolutionOptions(note, NOW))).toEqual([
      "dismissed",
      "content_hidden",
      "tutor_suspended",
      "booking_cancelled",
    ])
  })

  it("lets a profile report be dismissed or end in a suspension, with no booking choices", () => {
    expect(values(resolutionOptions(report("tutor_profile", null), NOW))).toEqual(["dismissed", "tutor_suspended"])
  })

  it("offers the suspension from the states the server can suspend from", () => {
    for (const state of ["pending_review", "listed", "rejected"] as const) {
      const context = report("tutor_profile", null, { tutorListingState: state })
      expect(values(resolutionOptions(context, NOW)), state).toContain("tutor_suspended")
    }
  })

  it("does not offer the suspension for a tutor who is suspended, closed or still a draft", () => {
    for (const state of ["suspended", "closed", "draft"] as const) {
      const context = report("tutor_profile", null, { tutorListingState: state })
      expect(values(resolutionOptions(context, NOW)), state).toEqual(["dismissed"])
    }
  })

  it("still offers cancelling a booking whose tutor can no longer be suspended", () => {
    const context = report("booking", summary("accepted", 5), { tutorListingState: "closed" })
    expect(values(resolutionOptions(context, NOW))).toEqual(["dismissed", "booking_cancelled"])
  })

  it("checks a choice again at submit time: cancelling stops being offered once the session starts", () => {
    const booking = report("booking", summary("accepted", 1))
    const beforeStart = new Date(NOW.getTime())
    const afterStart = new Date(NOW.getTime() + 2 * HOUR)
    expect(resolutionStillOffered(booking, "booking_cancelled", beforeStart)).toBe(true)
    expect(resolutionStillOffered(booking, "booking_cancelled", afterStart)).toBe(false)
    expect(resolutionStillOffered(booking, "dismissed", afterStart)).toBe(true)
  })

  it("says how long until the session starts while cancelling is offered, and nothing otherwise", () => {
    expect(cancelWindowMs(report("booking", summary("accepted", 1)), NOW)).toBe(HOUR)
    expect(cancelWindowMs(report("booking", summary("accepted", -1)), NOW)).toBeNull()
    expect(cancelWindowMs(report("booking", summary("completed", 1)), NOW)).toBeNull()
    expect(cancelWindowMs(report("tutor_profile", null), NOW)).toBeNull()
    expect(cancelWindowMs(report("booking", summary("accepted", 1), { state: "actioned" }), NOW)).toBeNull()
  })

  it("lets review and reply reports hide the content", () => {
    for (const target of ["review", "review_reply"] as const) {
      expect(values(resolutionOptions(report(target, null), NOW))).toEqual([
        "dismissed",
        "content_hidden",
        "tutor_suspended",
      ])
    }
  })

  it("offers nothing once a report is resolved", () => {
    const done = report("booking", summary("accepted", 5), { state: "dismissed", resolution: "dismissed" })
    expect(resolutionOptions(done, NOW)).toEqual([])
  })

  it("gives every option a label and a line of help", () => {
    const all = resolutionOptions(report("booking", summary("awaiting_outcome", -3), { reason: "disputed_outcome" }), NOW)
    expect(all.length).toBeGreaterThan(0)
    for (const option of all) {
      expect(option.label.length).toBeGreaterThan(2)
      expect(option.help.length).toBeGreaterThan(10)
    }
  })

  it("says why a booking choice is missing instead of hiding it silently", () => {
    expect(resolutionUnavailable(report("booking", summary("awaiting_outcome", -3)), NOW)).toMatch(/started/)
    expect(resolutionUnavailable(report("booking", summary("accepted", 5)), NOW)).toBeNull()
    expect(resolutionUnavailable(report("tutor_profile", null), NOW)).toBeNull()
  })

  it("needs a note of at most the table's limit", () => {
    expect(resolutionNoteError("")).not.toBeNull()
    expect(resolutionNoteError("  ")).not.toBeNull()
    expect(resolutionNoteError("a".repeat(RESOLUTION_NOTE_MAX))).toBeNull()
    expect(resolutionNoteError("a".repeat(RESOLUTION_NOTE_MAX + 1))).not.toBeNull()
  })

  it("is ready only with a choice, a note within the limit, and a connection", () => {
    const choice = resolutionOptions(report("tutor_profile", null), NOW)[0]
    expect(resolveReadiness({ choice, note: "Checked.", online: true })).toEqual({ ready: true, hint: null })
    // A resolution is chosen and the note is blank: Resolve stays shut and says why.
    expect(resolveReadiness({ choice, note: "   ", online: true })).toEqual({
      ready: false,
      hint: "A note is needed before this can be recorded.",
    })
    expect(resolveReadiness({ choice: null, note: "Checked.", online: true })).toEqual({
      ready: false,
      hint: "Choose what should happen.",
    })
    expect(resolveReadiness({ choice, note: "Checked.", online: false })).toEqual({
      ready: false,
      hint: "You're offline. Reconnect to resolve.",
    })
    expect(resolveReadiness({ choice, note: "x".repeat(RESOLUTION_NOTE_MAX + 1), online: true }).ready).toBe(false)
    expect(resolveReadiness({ choice, note: "x".repeat(RESOLUTION_NOTE_MAX), online: true }).ready).toBe(true)
  })

  it("builds the A11 body from the choice and the trimmed note", () => {
    expect(resolveBody("content_hidden", "  Contact details.  ")).toEqual({
      resolution: "content_hidden",
      note: "Contact details.",
    })
  })

  it("asks for confirmation before the choices that cannot be taken back, not before dismissing", () => {
    expect(resolutionConfirm("dismissed")).toBeNull()
    expect(resolutionConfirm("tutor_suspended")?.body).toContain(SUSPEND_CONSEQUENCE)
    expect(resolutionConfirm("booking_cancelled")?.body).toMatch(/cancel/i)
    expect(resolutionConfirm("booking_completed")).not.toBeNull()
    expect(resolutionConfirm("content_hidden")).not.toBeNull()
  })
})

describe("X-07 who completed a booking, and the already-resolved refusal", () => {
  it("names each party in words, never the raw value", () => {
    expect(completedByLabel("student")).toBe("The student")
    expect(completedByLabel("parent")).toBe("The parent")
    expect(completedByLabel("tutor")).toBe("The tutor")
    expect(completedByLabel("platform_admin")).toBe("Lemely")
    for (const value of ["student", "parent", "tutor", "platform_admin"] as const) {
      expect(completedByLabel(value)).not.toMatch(/_|^[a-z]/)
    }
  })

  it("recognises only the 409 already_resolved", () => {
    const refusal = (status: number, code: string) => new ApiError(status, "x", { code, message: "x" })
    expect(isAlreadyResolved(refusal(409, "already_resolved"))).toBe(true)
    expect(isAlreadyResolved(refusal(409, "resolution_not_applicable"))).toBe(false)
    expect(isAlreadyResolved(new Error("already_resolved"))).toBe(false)
    expect(isAlreadyResolved(null)).toBe(false)
  })
})

describe("X-07 labels and ordering", () => {
  it("flags only a safety concern", () => {
    expect(isSafetyConcern({ reason: "safety_concern" })).toBe(true)
    expect(isSafetyConcern({ reason: "harassment" })).toBe(false)
  })

  it("labels every reason and every target in words", () => {
    const reasons = ["safety_concern", "inappropriate_content", "harassment", "spam", "fake_profile", "disputed_outcome", "other"] as const
    const targets = ["tutor_profile", "review", "review_reply", "booking", "booking_note"] as const
    expect(new Set(reasons.map(reportReasonLabel)).size).toBe(7)
    expect(new Set(targets.map(reportTargetLabel)).size).toBe(5)
    for (const label of [...reasons.map(reportReasonLabel), ...targets.map(reportTargetLabel)]) {
      expect(label).not.toMatch(/_/)
    }
  })

  it("names the reporter by party, never by name", () => {
    expect(reporterLabel("student")).toBe("A student")
    expect(reporterLabel("parent")).toBe("A parent")
    expect(reporterLabel("tutor")).toBe("The tutor")
  })

  it("tells the admin the thread view is logged", () => {
    expect(THREAD_VIEW_NOTICE).toMatch(/logged/i)
  })
})

describe("X-07 notes after a resolution", () => {
  const loaded: Note[] = [
    { noteId: "n1", authorParty: "student", authorName: "Sara Hassan", body: "Can we move to 5?", hidden: false, createdAt: "2026-10-28T10:00:00Z" },
  ]

  it("keeps the notes of the last read when A11 answers with none, because it never carries the thread", () => {
    expect(threadNotes(loaded, [], true)).toBe(loaded)
  })

  it("shows what the server sent whenever the report was read rather than resolved here", () => {
    expect(threadNotes(loaded, [], false)).toEqual([])
    const fresh: Note[] = [{ ...loaded[0], noteId: "n2" }]
    expect(threadNotes(loaded, fresh, false)).toBe(fresh)
    expect(threadNotes(loaded, fresh, true)).toBe(fresh)
  })
})

describe("X-07 notes thread: party labels, never a student's name", () => {
  const notes: Note[] = [
    {
      noteId: "n1",
      authorParty: "student",
      authorName: "Sara Hassan",
      body: "Can we move to 5?",
      hidden: false,
      createdAt: "2026-10-28T10:00:00Z",
    },
    {
      noteId: "n2",
      authorParty: "tutor",
      authorName: "Dina A.",
      body: "Call me on 0100 000 0000",
      hidden: true,
      createdAt: "2026-10-28T10:05:00Z",
    },
  ]

  it("labels a note by its party", () => {
    expect(noteLabel({ authorParty: "student" })).toBe("Student")
    expect(noteLabel({ authorParty: "tutor" })).toBe("Tutor")
  })

  it("keeps order, shows hidden bodies marked as hidden, and carries no author name", () => {
    const rows = adminNoteRows(notes)
    expect(rows.map((row) => row.label)).toEqual(["Student", "Tutor"])
    expect(rows[1].hidden).toBe(true)
    expect(rows[1].body).toBe("Call me on 0100 000 0000")
    expect(JSON.stringify(rows)).not.toContain("Sara")
    expect(JSON.stringify(rows)).not.toContain("Hassan")
    expect(JSON.stringify(rows)).not.toContain("Dina")
  })

  it("keeps a hidden note whose body is missing as an honest gap", () => {
    const rows = adminNoteRows([{ ...notes[1], body: null }])
    expect(rows[0].body).toBeNull()
    expect(rows[0].hidden).toBe(true)
  })
})

describe("X-07 snapshot and times", () => {
  it("flattens a snapshot into plain labelled lines", () => {
    expect(
      snapshotRows({ stars: 2, text: "Not good", authorParty: "student", modes: ["virtual", "in_person"], nested: { a: 1 } }),
    ).toEqual([
      { label: "Stars", value: "2" },
      { label: "Text", value: "Not good" },
      { label: "Author party", value: "student" },
      { label: "Modes", value: "virtual, in_person" },
      { label: "Nested", value: '{"a":1}' },
    ])
  })

  it("shows the name of a {code, name} value, alone or in a list, never its JSON", () => {
    expect(
      snapshotRows({
        area: { code: "maadi", name: "Maadi" },
        subjects: [
          { code: "0580", name: "Mathematics" },
          { code: "0625", name: "Physics" },
        ],
      }),
    ).toEqual([
      { label: "Area", value: "Maadi" },
      { label: "Subjects", value: "Mathematics, Physics" },
    ])
  })

  it("shows an empty snapshot value honestly", () => {
    expect(snapshotRows({ headline: null })).toEqual([{ label: "Headline", value: "Not set" }])
  })

  it("formats an instant in a named zone, with the zone shown", () => {
    const text = formatAdminInstant("2026-10-30T15:00:00Z", "Africa/Cairo")
    expect(text).toMatch(/30 Oct/)
    expect(text).toMatch(/17:00/)
  })
})

// ── Copy lint ───────────────────────────────────────────────────────────────

describe("the module's own sentences follow the product rules", () => {
  it("has no em dash, no exclamation mark and neither banned tutoring word", () => {
    const sentences = [
      CLOSE_CONFIRM,
      DECISION_COPY.close.consequence,
      SUSPEND_CONSEQUENCE,
      THREAD_VIEW_NOTICE,
      MOCK_EMAIL_TITLE,
      emailDeliveryNotice("mock")?.body ?? "",
      ...(["approve", "reject", "suspend", "close"] as const).flatMap((d) => [decisionNoteError(d, "") ?? ""]),
      ...(["dismissed", "content_hidden", "tutor_suspended", "booking_cancelled", "booking_completed"] as const).flatMap(
        (r) => {
          const confirm = resolutionConfirm(r)
          return confirm ? [confirm.title, confirm.body, confirm.confirmLabel] : []
        },
      ),
      ...resolutionOptions(report("booking", summary("awaiting_outcome", -3), { reason: "disputed_outcome" }), NOW).flatMap((o) => [o.label, o.help]),
    ].filter((sentence) => sentence !== "")
    expect(sentences.length).toBeGreaterThanOrEqual(15)
    for (const sentence of sentences) {
      expect(sentence).not.toMatch(/—|!|\b(?:improvements?|verified)\b/i)
    }
  })
})

// ── The five screens ────────────────────────────────────────────────────────

function ok<T>(data: T, extra: Record<string, unknown> = {}) {
  return {
    status: "success",
    fetchStatus: "idle",
    data,
    error: null,
    isPending: false,
    isError: false,
    isFetching: false,
    dataUpdatedAt: Date.now(),
    refetch: vi.fn(),
    ...extra,
  }
}

function failed(error: unknown) {
  return { status: "error", fetchStatus: "idle", data: undefined, error, isPending: false, isError: true, isFetching: false, dataUpdatedAt: 0, refetch: vi.fn() }
}

function loading() {
  return { status: "pending", fetchStatus: "fetching", data: undefined, error: null, isPending: true, isError: false, isFetching: true, dataUpdatedAt: 0, refetch: vi.fn() }
}

function render(element: ReactElement): string {
  return renderToStaticMarkup(
    h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, element)),
  )
}

function buttonHtml(markup: string, label: string): string {
  const match = new RegExp(`<button[^>]*>${label}</button>`).exec(markup)
  expect(match, `no <${label}> button in the markup`).not.toBeNull()
  return match![0]
}

beforeEach(() => {
  hooks.clicks.length = 0
  hooks.forms.length = 0
  hooks.review = hooks.idle()
  hooks.reply = hooks.idle()
  hooks.approve = hooks.idle()
  hooks.resolve = hooks.idle()
})

const DETAIL: AdminTutorDetail = {
  tutorId: "t1",
  publicName: "Dina A.",
  headline: "IGCSE Maths for nervous students",
  subjects: [{ code: "0580", name: "Mathematics" }],
  modes: ["virtual", "in_person"],
  area: { code: "maadi", name: "Maadi" },
  rating: { state: "new", average: null, count: 0 },
  bio: "I taught for ten years.",
  qualificationNote: "BSc Mathematics",
  otherModeNote: null,
  documentsSeen: false,
  availability: [{ isoWeekday: 2, startMinute: 960, endMinute: 1080 }],
  zone: "Africa/Cairo",
  zoneLabel: "Cairo time",
  listedSince: null,
  listingState: "pending_review",
  paused: false,
  indexable: true,
  submittedAt: "2026-10-27T10:00:00Z",
  reviewNote: null,
  evidence: [
    { evidenceId: "e1", filename: "degree.pdf", contentType: "application/pdf", sizeBytes: 2048, description: "Degree certificate", uploadedAt: "2026-10-26T10:00:00Z", signedUrl: "https://files.example/e1" },
    { evidenceId: "e2", filename: "reference.jpg", contentType: "image/jpeg", sizeBytes: 1_572_864, description: null, uploadedAt: "2026-10-26T10:05:00Z", signedUrl: "https://files.example/e2" },
  ],
  accountEmail: "dina@example.com",
  history: [{ decision: "rejected", documentsSeen: false, note: "Please add a reference.", createdAt: "2026-10-20T10:00:00Z" }],
  openReports: 0,
}

describe("X-04 screen", () => {
  const page = (emailDelivery: "provider" | "mock", items = [{ tutorId: "t1", publicName: "Dina A.", subjects: [{ code: "0580", name: "Mathematics" }], submittedAt: null }]) =>
    ok({ items, nextCursor: null, emailDelivery })

  it("shows the Email delivery: mock banner when A1 says mock", () => {
    hooks.tutors = page("mock")
    expect(render(h(TutorQueue))).toContain(MOCK_EMAIL_TITLE)
  })

  it("shows no banner when mail is really sent", () => {
    hooks.tutors = page("provider")
    expect(render(h(TutorQueue))).not.toContain("Email delivery")
  })

  it("lists each tutor with a link to X-05 and says when nothing was submitted", () => {
    hooks.tutors = page("provider")
    const markup = render(h(TutorQueue))
    expect(markup).toContain('href="/platform/tutors/t1"')
    expect(markup).toContain("Dina A.")
    expect(markup).toContain("Not submitted")
  })

  it("says the queue is empty, fails with a retry, and loads with a skeleton", () => {
    hooks.tutors = ok({ items: [], nextCursor: null, emailDelivery: "provider" })
    expect(render(h(TutorQueue))).toContain("No applications waiting")
    hooks.tutors = failed(new ApiError(500, "x"))
    expect(render(h(TutorQueue))).toContain("We couldn&#x27;t load the tutors")
    hooks.tutors = loading()
    const skeleton = render(h(TutorQueue))
    expect(skeleton).toContain('aria-label="Loading"')
    expect(skeleton).not.toContain("<table")
  })

  it("offers Load more when the server has another page", () => {
    hooks.tutors = ok({ items: [{ tutorId: "t1", publicName: "Dina A.", subjects: [], submittedAt: null }], nextCursor: "c2", emailDelivery: "provider" })
    expect(render(h(TutorQueue))).toContain("Load more")
  })
})

describe("X-05 screen", () => {
  it("keeps Approve disabled on arrival, with the reason beside it", () => {
    hooks.tutor = ok(DETAIL)
    const markup = render(h(TutorApplication))
    expect(buttonHtml(markup, "Approve")).toContain("disabled")
    expect(markup).toContain("2 files not opened yet.")
    expect(markup).toContain("I looked at the documents")
  })

  it("links each file to its download in a new tab without leaking the page", () => {
    hooks.tutor = ok(DETAIL)
    const markup = render(h(TutorApplication))
    expect(markup.match(/href="https:\/\/files\.example\/e\d"/g)).toHaveLength(2)
    expect(markup.match(/rel="noopener noreferrer"/g)).toHaveLength(2)
    expect(markup).toContain("degree.pdf")
    expect(markup).toContain("1.5 MB")
  })

  it("replaces dead links with a way to get new ones", () => {
    hooks.tutor = ok(DETAIL, { dataUpdatedAt: 0 })
    const markup = render(h(TutorApplication))
    expect(markup).toContain("The links have expired.")
    expect(markup).toContain("Get new links")
    expect(markup).not.toContain("Open file")
  })

  it("says so when no files were uploaded, and needs only the box", () => {
    hooks.tutor = ok({ ...DETAIL, evidence: [] })
    const markup = render(h(TutorApplication))
    expect(markup).toContain("has not uploaded any files")
    expect(markup).toContain('Tick &quot;I looked at the documents&quot; to continue.')
  })

  it("offers each state only its own decisions", () => {
    hooks.tutor = ok(DETAIL)
    let markup = render(h(TutorApplication))
    for (const label of ["Reject", "Suspend", "Close"]) expect(markup).toContain(`>${label}</button>`)
    hooks.tutor = ok({ ...DETAIL, listingState: "suspended" })
    markup = render(h(TutorApplication))
    expect(markup).toContain(">Reinstate</button>")
    expect(markup).not.toContain(">Reject</button>")
    hooks.tutor = ok({ ...DETAIL, listingState: "listed" })
    markup = render(h(TutorApplication))
    expect(markup).not.toContain("I looked at the documents")
    expect(markup).toContain(">Suspend</button>")
    hooks.tutor = ok({ ...DETAIL, listingState: "closed" })
    expect(render(h(TutorApplication))).toContain("No decisions are left")
  })

  it("shows the account email, the history with its note, and the open report count", () => {
    hooks.tutor = ok({ ...DETAIL, openReports: 2 })
    const markup = render(h(TutorApplication))
    expect(markup).toContain("dina@example.com")
    expect(markup).toContain("Please add a reference.")
    expect(markup).toContain("2 open reports")
  })

  it("sends nothing when the form is submitted while the gate is shut", () => {
    hooks.tutor = ok(DETAIL)
    render(h(TutorApplication))
    expect(hooks.forms).toHaveLength(1)
    const preventDefault = vi.fn()
    ;(hooks.forms[0].onSubmit as (event: { preventDefault: () => void }) => void)({ preventDefault })
    expect(preventDefault).toHaveBeenCalledTimes(1)
    expect(hooks.approve.mutate).not.toHaveBeenCalled()
  })

  it("fails with a retry when the profile cannot load", () => {
    hooks.tutor = failed(new ApiError(404, "x", { code: "not_found", message: "x" }))
    const markup = render(h(TutorApplication))
    expect(markup).toContain("We couldn&#x27;t load this tutor")
    expect(markup).toContain(TUTORING_ERROR_COPY.not_found.replace("'", "&#x27;"))
  })
})

describe("X-05 confirm sheet: the confirm button follows the note rule", () => {
  const dialog = (decision: "reject" | "suspend" | "close") =>
    render(h(DecisionDialog, { decision, tutorName: "Dina A.", pending: false, error: null, onConfirm: vi.fn(), onClose: vi.fn() }))

  it("keeps the confirm button disabled while a required note is blank", () => {
    for (const decision of ["reject", "suspend"] as const) {
      expect(buttonHtml(dialog(decision), DECISION_COPY[decision].confirmLabel), decision).toContain("disabled")
    }
  })

  it("leaves the confirm button enabled for a close, whose note is optional", () => {
    expect(buttonHtml(dialog("close"), DECISION_COPY.close.confirmLabel)).not.toContain("disabled")
  })

  it("says the close and suspend costs in the sheet", () => {
    expect(dialog("close")).toContain("outside a school")
    expect(dialog("suspend")).toContain("booked or shared with this tutor")
  })
})

describe("X-06 screen", () => {
  const review: ModerationItem = { kind: "review", itemId: "rev1", text: "Great tutor.", createdAt: "2026-10-29T09:00:00Z", revision: "0123456789abcdef" }
  const reply: ModerationItem = { kind: "reply", itemId: "rep1", text: "Thank you.", createdAt: "2026-10-29T10:00:00Z", revision: "fedcba9876543210" }

  function press(label: string) {
    const entry = hooks.clicks.find((click) => click.label === label)
    expect(entry, `no button "${label}"`).toBeDefined()
    entry!.onClick?.()
  }

  it("sends a review's revision with the decision the admin made", () => {
    hooks.moderation = ok({ items: [review, reply], nextCursor: null })
    render(h(Moderation))
    press("Approve this review text")
    expect(hooks.review.mutate).toHaveBeenCalledTimes(1)
    expect(hooks.review.mutate).toHaveBeenCalledWith(
      { reviewId: "rev1", body: { decision: "approved", revision: "0123456789abcdef" } },
      expect.anything(),
    )
    press("Reject this review text")
    expect(hooks.review.mutate).toHaveBeenLastCalledWith(
      { reviewId: "rev1", body: { decision: "rejected", revision: "0123456789abcdef" } },
      expect.anything(),
    )
  })

  it("sends a reply decision alone", () => {
    hooks.moderation = ok({ items: [review, reply], nextCursor: null })
    render(h(Moderation))
    press("Approve this reply")
    expect(hooks.reply.mutate).toHaveBeenCalledWith({ replyId: "rep1", body: { decision: "approved" } }, expect.anything())
    expect(hooks.review.mutate).not.toHaveBeenCalled()
  })

  it("shows the words, the kind and the date, and nothing about the author", () => {
    hooks.moderation = ok({ items: [review, reply], nextCursor: null })
    const markup = render(h(Moderation))
    expect(markup).toContain("Great tutor.")
    expect(markup).toContain("Review text")
    expect(markup).toContain("29 Oct 2026")
  })

  it("says the queue is empty", () => {
    hooks.moderation = ok({ items: [], nextCursor: null })
    expect(render(h(Moderation))).toContain("Nothing to moderate")
  })
})

describe("X-07 screens", () => {
  it("lists reports with a link each, and says when there are none", () => {
    hooks.reports = ok({
      items: [
        { reportId: "r1", targetType: "booking_note", reason: "safety_concern", state: "open", createdAt: "2026-10-29T09:00:00Z" },
        { reportId: "r2", targetType: "review", reason: "spam", state: "open", createdAt: "2026-10-28T09:00:00Z" },
      ],
      nextCursor: null,
    })
    const markup = render(h(Reports))
    expect(markup).toContain('href="/platform/reports/r1"')
    expect(markup).toContain("Safety concern")
    expect(markup).toContain("Session note")
    expect(markup.indexOf("r1")).toBeLessThan(markup.indexOf("r2"))
    hooks.reports = ok({ items: [], nextCursor: null })
    expect(render(h(Reports))).toContain("No open reports")
  })

  it("offers no cancellation once the booking has started, and says why", () => {
    hooks.report = ok(report("booking", summary("awaiting_outcome", -3, Date.now()), { reason: "disputed_outcome" }))
    const markup = render(h(ReportDetailScreen))
    expect(markup).not.toContain("Cancel the booking")
    expect(markup).toContain("Mark the session completed")
    expect(markup).toContain("already started")
  })

  it("offers cancellation before the start", () => {
    hooks.report = ok(report("booking", summary("accepted", 5, Date.now())))
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Cancel the booking")
    expect(markup).not.toContain("Mark the session completed")
    expect(markup).not.toContain("already started")
  })

  it("keeps the submit shut until a choice and a note exist", () => {
    hooks.report = ok(report("tutor_profile", null))
    const markup = render(h(ReportDetailScreen))
    expect(buttonHtml(markup, "Resolve report")).toContain("disabled")
    expect(markup).toContain("Choose what should happen.")
  })

  it("shows the thread with party labels and the view notice, never a student's name", () => {
    hooks.report = ok(
      report("booking_note", summary("accepted", 5, Date.now()), {
        notes: [
          { noteId: "n1", authorParty: "student", authorName: "Sara Hassan", body: "Can we move to 5?", hidden: false, createdAt: "2026-10-28T10:00:00Z" },
          { noteId: "n2", authorParty: "tutor", authorName: "Dina A.", body: "Call me", hidden: true, createdAt: "2026-10-28T10:05:00Z" },
        ],
      }),
    )
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Can we move to 5?")
    expect(markup).toContain("Student")
    expect(markup).toContain("Hidden from the student and tutor")
    expect(markup).toContain("Opening this report is logged")
    expect(markup).not.toContain("Sara")
    expect(markup).not.toContain("Hassan")
  })

  it("shows the notes of a resolved booking report and never says there are none", () => {
    const notes: Note[] = [
      { noteId: "n1", authorParty: "student", authorName: "Sara Hassan", body: "Can we move to 5?", hidden: false, createdAt: "2026-10-28T10:00:00Z" },
    ]
    hooks.report = ok(
      report("booking_note", summary("accepted", 5, Date.now()), {
        state: "actioned",
        resolution: "dismissed",
        resolutionNote: "Fine.",
        resolvedAt: "2026-10-30T09:00:00Z",
        notes,
      }),
    )
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Can we move to 5?")
    expect(markup).not.toContain("There are no notes on this booking.")
    expect(markup).toContain("Fine.")
    // and the honest empty state is still there for a thread that is empty
    hooks.report = ok(report("booking_note", summary("accepted", 5, Date.now()), { notes: [] }))
    expect(render(h(ReportDetailScreen))).toContain("There are no notes on this booking.")
  })

  it("says who completed the booking in words", () => {
    hooks.report = ok(report("booking", { ...summary("completed", -3, Date.now()), completedBy: "platform_admin" }))
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Marked completed by")
    expect(markup).toContain("Lemely")
    expect(markup).not.toContain("platform admin")
  })

  it("offers to reload the report after an already-resolved refusal, and only then", () => {
    const refetch = vi.fn()
    hooks.report = ok(report("tutor_profile", null), { refetch })
    hooks.resolve = {
      ...hooks.idle(),
      isError: true,
      error: new ApiError(409, "x", { code: "already_resolved", message: "x" }),
    }
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain(TUTORING_ERROR_COPY.already_resolved)
    expect(buttonHtml(markup, "Reload this report")).not.toContain("disabled")
    hooks.clicks.find((click) => click.label === "Reload this report")?.onClick?.()
    expect(refetch).toHaveBeenCalledTimes(1)

    hooks.clicks.length = 0
    hooks.resolve = {
      ...hooks.idle(),
      isError: true,
      error: new ApiError(409, "x", { code: "resolution_not_applicable", message: "x" }),
    }
    const other = render(h(ReportDetailScreen))
    expect(other).toContain(TUTORING_ERROR_COPY.resolution_not_applicable)
    expect(other).not.toContain("Reload this report")
  })

  it("shows the outcome of a resolved report instead of the form", () => {
    hooks.report = ok(
      report("review", null, { state: "actioned", resolution: "content_hidden", resolutionNote: "Phone number.", resolvedAt: "2026-10-30T09:00:00Z" }),
    )
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Content hidden")
    expect(markup).toContain("Phone number.")
    expect(markup).not.toContain("Resolve report")
  })

  it("names the reporter by party and shows the snapshot", () => {
    hooks.report = ok(report("review", null, { reporterParty: "parent", snapshot: { stars: 1, text: "Rude." } }))
    const markup = render(h(ReportDetailScreen))
    expect(markup).toContain("Reported by a parent on")
    expect(markup).toContain("Rude.")
  })
})
