import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement as h, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { postLoginTarget } from "@/lib/auth/postLoginTarget"
import type { ChildSummary } from "@/lib/parentTypes"
import { GRANT_STATUS_VIEW } from "@/lib/tutoring/accessView"
import { TutorFailure } from "@/components/tutoring/tutor-profile-view"
import { childErrorFor } from "@/components/tutoring/booking-form"
import { TUTOR_UNAVAILABLE_MESSAGE, bookingRefusalOf } from "@/lib/tutoring/bookingErrors"
import { PARENT_TUTORS_PATH as PARENT_TUTORS_PATH_FROM_NEXT, parentNextTarget as parentNextFromModule } from "@/lib/tutoring/parentNext"
import {
  parentBookHref,
  parentChildTutoringHref,
  parentDirectoryHref,
  parentGrantRowView,
  parentNextTarget,
  parentSessionHref,
  parentSharingLine,
  parentTutorAccessHref,
  parentTutorHref,
  preselectedChild,
  resolveLinkedChild,
  tutorsFromBookings,
} from "@/lib/tutoring/parentTutoring"
import { parentNotesFootnote, sessionActions } from "@/lib/tutoring/sessionView"
import type { AccessLogEntry, Booking, Grant, GrantStatus, ViewerAction } from "@/lib/tutoringTypes"
import { ChildTutorAccess } from "@/portals/parent/screens/tutoring/ChildTutorAccess"
import { ChildTutoring } from "@/portals/parent/screens/tutoring/ChildTutoring"
import { ParentFindTutor, ParentBookSession, ParentTutorProfile } from "@/portals/parent/screens/tutoring/ParentFindTutor"
import { ParentSessionDetail } from "@/portals/parent/screens/tutoring/ParentSessionDetail"
import { stripComments } from "./support/jsxSource"

/*
 * T27 · the parent's tutoring screens (P-05 child's tutoring, P-06 session
 * detail, P-07 find and book a tutor, P-08 who the child shares with).
 *
 * The runner is node-only (D3.20), so the screens are drawn with
 * `react-dom/server` on top of mocked hooks, and where a behaviour sits in a
 * callback (the cancel wiring, the props a shared component was given) the
 * mocked component records its props. What is mocked is never the code under
 * test: the hooks (network), `Modal` (a portal), `NotesThread` and
 * `DirectoryView` (recorded), `useOnlineStatus`.
 *
 * What these tests guard:
 *   1. a parent's booking form never has a first note, and never sends one;
 *   2. Cancel and Mark as completed show only for the parent who made the request;
 *   3. P-08 has no way to stop sharing, and says everything in the third person;
 *   4. P-07 gets the child from the LINKED LIST, and a hidden tutor reads as the
 *      one generic answer, never as a block;
 *   5. G-17's "Sign in to book" target lands a parent in the parent portal.
 */

const WEB = join(import.meta.dirname, "..", "..")
const src = (path: string) => stripComments(readFileSync(join(WEB, "src", path), "utf8"))
const SPEC = readFileSync(join(WEB, "..", "docs", "tutoring", "SPEC.md"), "utf8")
const PARENT_SPEC = SPEC.slice(SPEC.indexOf("### Parent (P)"), SPEC.indexOf("### Platform admin (X)"))

// ── Mocks ───────────────────────────────────────────────────────────────────

type Query = {
  status: "pending" | "error" | "success"
  data: unknown
  error: unknown
  isPending: boolean
  isError: boolean
  isSuccess: boolean
  fetchStatus: "fetching" | "idle"
  refetch: () => void
}

function ok(data: unknown): Query {
  return { status: "success", data, error: null, isPending: false, isError: false, isSuccess: true, fetchStatus: "idle", refetch: () => undefined }
}
function failed(error: unknown): Query {
  return { status: "error", data: undefined, error, isPending: false, isError: true, isSuccess: false, fetchStatus: "idle", refetch: () => undefined }
}
function pending(): Query {
  return { status: "pending", data: undefined, error: null, isPending: true, isError: false, isSuccess: false, fetchStatus: "fetching", refetch: () => undefined }
}

const mocks = vi.hoisted(() => ({
  children: null as unknown,
  upcoming: null as unknown,
  past: null as unknown,
  booking: null as unknown,
  notes: null as unknown,
  grants: null as unknown,
  log: null as unknown,
  profile: null as unknown,
  bookingsCalls: [] as Array<[string, unknown]>,
  notesCalls: [] as Array<[string, string]>,
  cancel: { mutateAsync: undefined as unknown, isPending: false, error: null, reset: () => undefined },
  complete: { mutateAsync: undefined as unknown, isPending: false, error: null, reset: () => undefined },
  report: { mutate: () => undefined, isPending: false, isSuccess: false, error: null, reset: () => undefined },
  create: { mutate: () => undefined, isPending: false, isError: false, error: null },
  seen: {
    view: [] as Array<Record<string, any>>,
    form: [] as Array<Record<string, any>>,
    directory: [] as Array<Record<string, any>>,
    thread: [] as Array<Record<string, any>>,
  },
}))

vi.mock("@/lib/hooks/useParentApi", () => ({ useChildren: () => mocks.children }))

vi.mock("@/lib/hooks/useTutoringApi", () => ({
  useParentChildBookings: (childId: string, params: { when: string }) => {
    mocks.bookingsCalls.push([childId, params])
    return params.when === "past" ? mocks.past : mocks.upcoming
  },
  useParentChildBooking: () => mocks.booking,
  useParentChildBookingNotes: (childId: string, bookingId: string) => {
    mocks.notesCalls.push([childId, bookingId])
    return mocks.notes
  },
  useCancelParentChildBooking: () => mocks.cancel,
  useCompleteParentChildBooking: () => mocks.complete,
  useParentChildTutorGrants: () => mocks.grants,
  useParentChildTutorAccessLog: () => mocks.log,
  useCreateTutoringReport: () => mocks.report,
  useTutorProfile: () => mocks.profile,
  useTutorSlots: () => pending(),
  useCreateBooking: () => mocks.create,
}))

vi.mock("@/lib/online", () => ({ useOnlineStatus: () => true, isOnline: () => true }))

vi.mock("@/components/ui/modal", () => ({
  Modal: (props: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    props.open
      ? h("div", { role: "dialog" }, h("h2", null, props.title as never), props.children as never, props.footer as never)
      : null,
}))

vi.mock("@/components/ui/notes-thread", () => ({
  NotesThread: (props: Record<string, any>) => {
    mocks.seen.thread.push(props)
    return null
  },
}))

vi.mock("@/components/tutoring/directory-view", () => ({
  DirectoryView: (props: Record<string, any>) => {
    mocks.seen.directory.push(props)
    return null
  },
}))

vi.mock("@/components/tutoring/session-detail-view", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/components/tutoring/session-detail-view")>()
  return {
    ...real,
    SessionDetailView: (props: Record<string, any>) => {
      mocks.seen.view.push(props)
      return h(real.SessionDetailView, props as never)
    },
  }
})

vi.mock("@/components/tutoring/booking-form", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/components/tutoring/booking-form")>()
  return {
    ...real,
    BookingForm: (props: Record<string, any>) => {
      mocks.seen.form.push(props)
      return h(real.BookingForm, props as never)
    },
  }
})

vi.mock("@/components/tutoring/tutor-profile-view", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/components/tutoring/tutor-profile-view")>()
  return {
    ...real,
    TutorProfileView: (props: { actions?: unknown }) => h("div", null, props.actions as never),
    TutorOutcomes: () => null,
    ReviewsSection: () => null,
  }
})

// ── Fixtures ────────────────────────────────────────────────────────────────

function child(childId: string, displayName: string): ChildSummary {
  return { childId, displayName, classes: [], statusLine: "", trend: null, lastActivityAt: null } as unknown as ChildSummary
}
const MAYA = child("c1", "Maya R.")
const OMAR = child("c2", "Omar R.")

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
    student: { studentId: "c1", displayName: "Maya R." },
    requestedBy: "parent",
    subject: { code: "0580", name: "Mathematics" },
    mode: "virtual",
    startsAt: "2026-01-08T15:00:00Z",
    endsAt: "2026-01-08T16:00:00Z",
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
  } as Booking
}

function tutorOf(id: string, name: string): Booking["tutor"] {
  return { ...booking().tutor, tutorId: id, publicName: name }
}

function grant(status: GrantStatus, id = "g1", tutor = booking().tutor): Grant {
  return {
    grantId: id,
    tutor,
    createdAt: "2025-12-01T10:00:00Z",
    revokedAt: status === "active" ? null : "2026-01-02T10:00:00Z",
    status,
    scope: "all_subjects_derived",
    alsoTeachesClasses: [],
  }
}

const DETAIL: AccessLogEntry = { tutorId: "t1", tutorName: "Nour A.", action: "detail", accessedAt: "2026-01-05T12:00:00Z" }
const LIST: AccessLogEntry = { tutorId: null, tutorName: "Sami K.", action: "list", accessedAt: "2026-01-04T12:00:00Z" }

const TUTOR_PROFILE = {
  tutorId: "t1",
  publicName: "Nour A.",
  subjects: [{ code: "0580", name: "Mathematics" }],
  modes: ["virtual"],
  zone: "Africa/Cairo",
  zoneLabel: "Cairo time",
  otherModeNote: null,
}

function reset() {
  mocks.children = ok({ children: [MAYA, OMAR] })
  mocks.upcoming = ok({ items: [], nextCursor: null })
  mocks.past = ok({ items: [], nextCursor: null })
  mocks.booking = ok(booking())
  mocks.notes = ok({ items: [], nextCursor: null, canPost: false })
  mocks.grants = ok({ items: [] })
  mocks.log = ok({ items: [], nextCursor: null })
  mocks.profile = ok(TUTOR_PROFILE)
  mocks.bookingsCalls.length = 0
  mocks.notesCalls.length = 0
  mocks.cancel = { mutateAsync: vi.fn(async () => undefined), isPending: false, error: null, reset: () => undefined }
  mocks.complete = { mutateAsync: vi.fn(async () => undefined), isPending: false, error: null, reset: () => undefined }
  for (const list of Object.values(mocks.seen)) list.length = 0
}
beforeEach(reset)

function renderAt(url: string, pattern: string, element: ReactElement): string {
  return renderToStaticMarkup(
    h(MemoryRouter, { initialEntries: [url] }, h(Routes, null, h(Route, { path: pattern, element }))),
  )
}

/** The visible words of some markup: tags dropped, entities decoded. */
function words(html: string): string {
  return html
    .replace(/<[^>]*>/g, "\n")
    .replaceAll("&#x27;", "'")
    .replaceAll("&quot;", '"')
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&")
}

/** Every `href` in some markup. */
function hrefs(html: string): string[] {
  return [...html.matchAll(/href="([^"]*)"/g)].map((m) => m[1].replaceAll("&amp;", "&"))
}

// ── 1 · addresses and the post-login target ────────────────────────────────

describe("the parent's tutoring addresses", () => {
  it("builds every address the screens link to", () => {
    expect(parentTutorHref("t 1")).toBe("/parent/tutors/t%201")
    expect(parentBookHref("t1")).toBe("/parent/tutors/t1/book")
    expect(parentBookHref("t1", "c1")).toBe("/parent/tutors/t1/book?child=c1")
    expect(parentDirectoryHref()).toBe("/parent/tutors")
    expect(parentDirectoryHref("c1")).toBe("/parent/tutors?child=c1")
    expect(parentChildTutoringHref("c1")).toBe("/parent/children/c1/tutoring")
    expect(parentSessionHref("c1", "b1")).toBe("/parent/children/c1/sessions/b1")
    expect(parentTutorAccessHref("c1")).toBe("/parent/children/c1/tutor-access")
  })
})

describe("G-17 'Sign in to book' for a parent", () => {
  const ID = "0f8fad5b-d9cb-469f-a165-70867728950e"

  it("maps the student target to the parent's tutor page, and the parent portal accepts it", () => {
    const next = parentNextTarget(`/student/tutors/${ID}`)
    expect(next).toBe(`/parent/tutors/${ID}`)
    expect(postLoginTarget({ next, from: undefined, role: "parent" })).toBe(`/parent/tutors/${ID}`)
  })

  it("leaves every other address as it was, and never invents one", () => {
    expect(parentNextTarget(null)).toBeNull()
    expect(parentNextTarget("/student/tutors")).toBe("/student/tutors")
    expect(parentNextTarget(`/student/tutors/${ID}/book`)).toBe(`/student/tutors/${ID}/book`)
    expect(parentNextTarget("/parent/children/c1")).toBe("/parent/children/c1")
    expect(parentNextTarget("//evil.example/student/tutors/x")).toBe("//evil.example/student/tutors/x")
  })

  it("maps only a real tutor id, not any segment", () => {
    for (const segment of ["x", "not-a-uuid", "..%2F..", "0f8fad5b-d9cb-469f-a165-70867728950", `${ID}x`]) {
      expect(parentNextTarget(`/student/tutors/${segment}`), segment).toBe(`/student/tutors/${segment}`)
    }
    expect(parentNextTarget(`/student/tutors/${ID.toUpperCase()}`)).toBe(`/parent/tutors/${ID.toUpperCase()}`)
  })

  it("is the import-free module's function, re-exported here", () => {
    expect(parentNextTarget).toBe(parentNextFromModule)
    expect(PARENT_TUTORS_PATH_FROM_NEXT).toBe("/parent/tutors")
  })
})

// ── 2 · the child comes from the linked list ───────────────────────────────

describe("resolving the child from the linked list", () => {
  const linked = [MAYA, OMAR]

  it("finds a linked child by id and nothing else", () => {
    expect(resolveLinkedChild(linked, "c2")).toBe(OMAR)
    expect(resolveLinkedChild(linked, "c3")).toBeNull()
    expect(resolveLinkedChild(linked, "")).toBeNull()
    expect(resolveLinkedChild([], "c1")).toBeNull()
  })

  it("preselects a requested child only when linked; the sole child when there is one; otherwise none", () => {
    expect(preselectedChild(linked, "c2")).toBe(OMAR)
    expect(preselectedChild(linked, "evil")).toBeNull()
    expect(preselectedChild(linked, null)).toBeNull()
    expect(preselectedChild([MAYA], null)).toBe(MAYA)
    expect(preselectedChild([MAYA], "evil")).toBe(MAYA)
    expect(preselectedChild([], "c1")).toBeNull()
  })
})

// ── 3 · P-05: tutors come from bookings ────────────────────────────────────

describe("tutorsFromBookings", () => {
  it("lists each tutor once, in the order seen, with the subjects of their sessions", () => {
    const rows = tutorsFromBookings([
      booking({ bookingId: "a", tutor: tutorOf("t1", "Nour A."), subject: { code: "0580", name: "Mathematics" } }),
      booking({ bookingId: "b", tutor: tutorOf("t2", "Sami K."), subject: { code: "0625", name: "Physics" } }),
      booking({ bookingId: "c", tutor: tutorOf("t1", "Nour A."), subject: { code: "0606", name: "Additional Mathematics" } }),
      booking({ bookingId: "d", tutor: tutorOf("t1", "Nour A."), subject: { code: "0580", name: "Mathematics" } }),
    ])
    expect(rows.map((r) => r.tutorId)).toEqual(["t1", "t2"])
    expect(rows[0]).toMatchObject({ tutorName: "Nour A.", href: "/parent/tutors/t1", subjectLine: "Mathematics, Additional Mathematics" })
    expect(rows[1]).toMatchObject({ tutorName: "Sami K.", subjectLine: "Physics" })
  })

  it("keeps the chosen child on each tutor's link, so a parent of several stays on the same child", () => {
    const rows = tutorsFromBookings([booking({ tutor: tutorOf("t1", "Nour A.") })], "c2")
    expect(rows[0].href).toBe("/parent/tutors/t1?child=c2")
  })

  it("does not count a tutor who only declined, expired or was cancelled", () => {
    const rows = tutorsFromBookings([
      booking({ tutor: tutorOf("t1", "A"), effectiveState: "declined" }),
      booking({ tutor: tutorOf("t2", "B"), effectiveState: "expired" }),
      booking({ tutor: tutorOf("t3", "C"), effectiveState: "cancelled" }),
      booking({ tutor: tutorOf("t4", "D"), effectiveState: "requested" }),
      booking({ tutor: tutorOf("t5", "E"), effectiveState: "completed" }),
      booking({ tutor: tutorOf("t6", "F"), effectiveState: "no_show" }),
      booking({ tutor: tutorOf("t7", "G"), effectiveState: "awaiting_outcome" }),
    ])
    expect(rows.map((r) => r.tutorId)).toEqual(["t4", "t5", "t6", "t7"])
  })
})

describe("P-05 · child's tutoring", () => {
  const draw = () => renderAt("/parent/children/c1/tutoring", "/parent/children/:childId/tutoring", h(ChildTutoring))

  it("links on to P-08 and P-07 for this child, in the SPEC's words", () => {
    const html = draw()
    const text = words(html)
    expect(text).toContain("Who Maya R. shares progress with")
    expect(text).toContain("Find a tutor for Maya R.")
    expect(hrefs(html)).toContain("/parent/children/c1/tutor-access")
    expect(hrefs(html)).toContain("/parent/tutors?child=c1")
  })

  it("says the child has no sessions when there are none", () => {
    expect(words(draw())).toContain("Maya R. has no tutoring sessions.")
  })

  it("lists sessions that open P-06 and the child's tutors that open P-07", () => {
    mocks.upcoming = ok({ items: [booking()], nextCursor: null })
    const html = draw()
    expect(hrefs(html)).toContain("/parent/children/c1/sessions/b1")
    expect(hrefs(html)).toContain("/parent/tutors/t1?child=c1")
    expect(words(html)).not.toContain("has no tutoring sessions")
  })

  it("asks for the linked child's sessions and no one else's", () => {
    draw()
    expect(mocks.bookingsCalls.length).toBeGreaterThan(0)
    expect(new Set(mocks.bookingsCalls.map(([id]) => id))).toEqual(new Set(["c1"]))
  })

  it("is a plain not-found for a child who is not on the linked list", () => {
    const html = renderAt("/parent/children/zzz/tutoring", "/parent/children/:childId/tutoring", h(ChildTutoring))
    expect(words(html)).toContain("We couldn't find this child")
    expect(html.match(/<h1[ >]/g) ?? []).toHaveLength(1)
    expect(mocks.bookingsCalls).toEqual([])
  })

  it("shows a skeleton while loading and an error with a retry when the list fails", () => {
    mocks.upcoming = pending()
    expect(draw()).toContain('aria-label="Loading"')
    mocks.upcoming = failed(new ApiError(500, "boom"))
    expect(words(draw())).toContain("We couldn't load")
  })
})

// ── 4 · P-06: actions only for the parent who asked ────────────────────────

describe("P-06 · session detail", () => {
  const draw = (id = "b1") =>
    renderAt(`/parent/children/c1/sessions/${id}`, "/parent/children/:childId/sessions/:bookingId", h(ParentSessionDetail))

  it("shows Cancel only when this parent requested the session and cancel is allowed", () => {
    mocks.booking = ok(booking({ requestedBy: "parent", allowedActions: ["cancel"] }))
    expect(words(draw())).toContain("Cancel session")
    mocks.booking = ok(booking({ requestedBy: "student", allowedActions: ["cancel"] }))
    expect(words(draw())).not.toContain("Cancel session")
    mocks.booking = ok(booking({ requestedBy: "parent", allowedActions: [] }))
    expect(words(draw())).not.toContain("Cancel session")
  })

  it("shows Mark as completed only for the requesting parent with complete allowed", () => {
    const base = { effectiveState: "awaiting_outcome" as const }
    mocks.booking = ok(booking({ ...base, requestedBy: "parent", allowedActions: ["complete"] }))
    expect(words(draw())).toContain("Mark as completed")
    mocks.booking = ok(booking({ ...base, requestedBy: "student", allowedActions: ["complete"] }))
    expect(words(draw())).not.toContain("Mark as completed")
    mocks.booking = ok(booking({ ...base, requestedBy: "parent", allowedActions: [] }))
    expect(words(draw())).not.toContain("Mark as completed")
  })

  it("agrees with sessionActions for every combination of requester and action", () => {
    const actions: ViewerAction[][] = [[], ["cancel"], ["complete"], ["cancel", "complete"], ["post_note", "review"]]
    let cases = 0
    for (const requestedBy of ["parent", "student"] as const) {
      for (const allowedActions of actions) {
        const own = requestedBy === "parent"
        const got = sessionActions({ requestedBy, allowedActions }, "parent")
        expect(got.cancel).toBe(own && allowedActions.includes("cancel"))
        expect(got.complete).toBe(own && allowedActions.includes("complete"))
        expect(got.postNote).toBe(false)
        expect(got.review).toBe(false)
        cases += 1
      }
    }
    expect(cases).toBe(10)
  })

  it("hands the shared view the parent's wiring and none of the student's", () => {
    mocks.booking = ok(booking({ requestedBy: "parent", allowedActions: ["cancel", "post_note", "review"] }))
    draw()
    const props = mocks.seen.view.at(-1)
    expect(props, "the shared view was never drawn").toBeDefined()
    expect(props!.viewer).toBe("parent")
    expect(props!.tutorHref).toBe("/parent/tutors/t1?child=c1")
    expect(props!.countingHref).toBeUndefined()
    expect(props!.reviews).toBeUndefined()
    expect(props!.safetyNotice).toBeUndefined()
    expect(props!.notes.post).toBeUndefined()
    expect(props!.notes.canPost).toBe(false)
  })

  it("draws a thread that cannot post, with the SPEC's footnote", () => {
    mocks.booking = ok(booking({ allowedActions: ["post_note"] }))
    const text = words(draw())
    const thread = mocks.seen.thread.at(-1)
    expect(thread!.canPost).toBe(false)
    expect(thread!.onPost).toBeUndefined()
    expect(thread!.footnote).toBe(parentNotesFootnote("Maya R."))
    expect(text).toContain("Report this session")
  })

  it("cancel and complete go to the parent routes with this child and this booking", async () => {
    mocks.booking = ok(booking({ requestedBy: "parent", allowedActions: ["cancel", "complete"] }))
    draw()
    const props = mocks.seen.view.at(-1)!
    await props.cancel.run()
    await props.complete.run()
    expect(mocks.cancel.mutateAsync).toHaveBeenCalledWith({ childId: "c1", bookingId: "b1" })
    expect(mocks.complete.mutateAsync).toHaveBeenCalledWith({ childId: "c1", bookingId: "b1" })
    expect(mocks.notesCalls.every(([id, b]) => id === "c1" && b === "b1")).toBe(true)
    expect(mocks.notesCalls.length).toBeGreaterThan(0)
  })

  it("has no back link of its own (the shell's trail leads to P-05), and says so plainly when the session is not found", () => {
    expect(hrefs(draw())).not.toContain("/parent/children/c1/tutoring")
    mocks.booking = failed(new ApiError(404, "not found", { code: "not_found" }))
    const text = words(draw())
    expect(text).toContain("We couldn't find this session")
    expect(text).not.toMatch(/block/i)
  })

  it("has a loading state", () => {
    mocks.booking = pending()
    expect(words(draw())).toContain("Session")
  })
})

// ── 5 · P-07: find and book for the child ──────────────────────────────────

describe("P-07 · the booking form for a parent", () => {
  const draw = (query = "") =>
    renderAt(`/parent/tutors/t1/book${query}`, "/parent/tutors/:tutorId/book", h(ParentBookSession))

  it("is the shared form in its parent audience, with no first note and no safety notice", () => {
    const text = words(draw())
    const props = mocks.seen.form.at(-1)
    expect(props, "the booking form was never drawn").toBeDefined()
    expect(props!.audience).toBe("parent")
    expect(props!.safetyNoticeOpen).toBe(false)
    expect(text).not.toContain("First note")
    expect(text).not.toMatch(/firstNote/i)
    expect(text).not.toContain("Before your first session")
  })

  it("the shared form only ever sends a first note for a student (source guard)", () => {
    const form = src("components/tutoring/booking-form.tsx")
    const lines = form.split("\n").filter((line) => line.includes("firstNote"))
    expect(lines.length).toBeGreaterThan(0)
    const sends = lines.filter((line) => /body\.firstNote\s*=/.test(line))
    expect(sends).toHaveLength(1)
    expect(sends[0]).toMatch(/audience === "student"/)
  })

  it("offers a 'Booking for' selector made of the linked children and nothing typed", () => {
    const html = draw()
    const props = mocks.seen.form.at(-1)!
    expect(words(html)).toContain("Booking for")
    expect(html).toContain('value="c1"')
    expect(html).toContain('value="c2"')
    expect(words(html)).toContain("Maya R.")
    expect(words(html)).toContain("Omar R.")
    expect(props.childPicker).toBeDefined()
    expect(props.student).toBeUndefined()
    const code = src("portals/parent/screens/tutoring/ParentFindTutor.tsx")
    expect(code).not.toMatch(/studentId\s*[:=]/)
    expect(code).not.toMatch(/<Input\b/)
  })

  it("takes the child from ?child= only when that child is linked", () => {
    draw("?child=c2")
    expect(mocks.seen.form.at(-1)!.student).toEqual({ id: "c2", name: "Omar R." })
    draw("?child=evil")
    expect(mocks.seen.form.at(-1)!.student).toBeUndefined()
  })

  it("picks the only child, from the list, whatever the address says", () => {
    mocks.children = ok({ children: [MAYA] })
    draw("?child=evil")
    expect(mocks.seen.form.at(-1)!.student).toEqual({ id: "c1", name: "Maya R." })
  })

  it("sends a booked request to P-06 for the booking's own student, and a hidden tutor to the parent directory", () => {
    draw()
    const props = mocks.seen.form.at(-1)!
    expect(props.bookedPath(booking({ bookingId: "b9", student: { studentId: "c2", displayName: "Omar R." } }))).toBe(
      "/parent/children/c2/sessions/b9",
    )
    expect(props.directoryPath).toBe("/parent/tutors")
  })

  it("with no linked child explains how to link one instead of showing the form", () => {
    mocks.children = ok({ children: [] })
    const text = words(draw())
    expect(mocks.seen.form).toHaveLength(0)
    expect(text).toContain("Link a child to book")
    expect(text).toContain("Parent access")
  })

  it("has loading and error states for the tutor and for the children", () => {
    mocks.profile = pending()
    expect(words(draw())).toContain("Book a session")
    mocks.profile = ok(TUTOR_PROFILE)
    mocks.children = failed(new ApiError(500, "boom"))
    expect(words(draw())).toContain("We couldn't load your children")
  })
})

describe("P-07 · a hidden tutor is one generic answer", () => {
  it("reads a 404 as 'not taking bookings', and never mentions a block", () => {
    const refusal = bookingRefusalOf(new ApiError(404, "not found"))
    expect(refusal?.message).toBe(TUTOR_UNAVAILABLE_MESSAGE)
    expect(refusal?.message).not.toMatch(/block/i)
  })

  it("the profile screen shows that answer with a way back to the parent directory", () => {
    mocks.profile = failed(new ApiError(404, "not found", { code: "not_found" }))
    const html = renderAt("/parent/tutors/t1", "/parent/tutors/:tutorId", h(ParentTutorProfile))
    expect(words(html)).toContain(TUTOR_UNAVAILABLE_MESSAGE)
    expect(words(html)).not.toMatch(/block/i)
    expect(hrefs(html)).toContain("/parent/tutors")
    expect(html.match(/<h1[ >]/g) ?? []).toHaveLength(1)
  })

  it("the booking screen shows that answer for a 404 on the tutor", () => {
    mocks.profile = failed(new ApiError(404, "not found"))
    const html = renderAt("/parent/tutors/t1/book", "/parent/tutors/:tutorId/book", h(ParentBookSession))
    expect(words(html)).toContain(TUTOR_UNAVAILABLE_MESSAGE)
    expect(words(html)).not.toMatch(/block/i)
    expect(html.match(/<h1[ >]/g) ?? []).toHaveLength(1)
  })
})

describe("P-07 · the directory and a tutor's page", () => {
  it("lists tutors in the parent shell and keeps the chosen child on every link", () => {
    renderAt("/parent/tutors?child=c2&subject=0580", "/parent/tutors", h(ParentFindTutor))
    const props = mocks.seen.directory.at(-1)
    expect(props, "the directory was never drawn").toBeDefined()
    expect(props!.audience).toBe("member")
    expect(props!.tutorPath("t1")).toBe("/parent/tutors/t1?child=c2")
    expect(props!.filters.subject).toBe("0580")
    renderAt("/parent/tutors", "/parent/tutors", h(ParentFindTutor))
    expect(mocks.seen.directory.at(-1)!.tutorPath("t1")).toBe("/parent/tutors/t1")
  })

  it("a tutor's page offers Book and Report, and no Share, Block or safety notice", () => {
    const html = renderAt("/parent/tutors/t1?child=c1", "/parent/tutors/:tutorId", h(ParentTutorProfile))
    const text = words(html)
    expect(text).toContain("Book a session")
    expect(text).toContain("Report")
    expect(hrefs(html)).toContain("/parent/tutors/t1/book?child=c1")
    expect(text).not.toContain("Share my progress")
    expect(text).not.toContain("Block")
    const code = src("portals/parent/screens/tutoring/ParentFindTutor.tsx")
    expect(code).not.toMatch(/BlockSheet|ShareProgressSheet|SafetyNoticeSheet|useCreateTutoringBlock|useCreateTutorGrant/)
  })
})

describe("P-07 · the 'Booking for' error", () => {
  const draw = (query = "") =>
    renderAt(`/parent/tutors/t1/book${query}`, "/parent/tutors/:tutorId/book", h(ParentBookSession))

  it("is shown only while no child is chosen, so a picked child clears 'Choose a child.'", () => {
    expect(childErrorFor("Choose a child.", undefined)).toBe("Choose a child.")
    expect(childErrorFor("Choose a child.", { id: "c1", name: "Maya R." })).toBeUndefined()
    expect(childErrorFor(undefined, undefined)).toBeUndefined()
  })

  it("is handed to the child select, which links it with aria-invalid and aria-describedby", () => {
    draw()
    const picker = mocks.seen.form.at(-1)!.childPicker
    expect(typeof picker, "the picker must take the error").toBe("function")
    const plain = renderToStaticMarkup(picker(undefined))
    expect(plain).not.toContain("aria-invalid")
    const html = renderToStaticMarkup(picker("Choose a child."))
    expect(html).toContain('aria-invalid="true"')
    expect(html).toMatch(/aria-describedby="([^"]+-error)"/)
    const id = /aria-describedby="([^"]+)"/.exec(html)![1]
    expect(html).toContain(`id="${id}"`)
    expect(words(html)).toContain("Choose a child.")
  })
})

describe("a tutor page that failed has one h1", () => {
  const draw = (heading?: string | false) =>
    renderAt(
      "/x",
      "/x",
      h(TutorFailure, {
        error: new ApiError(404, "not found"),
        onRetry: () => undefined,
        directoryPath: "/parent/tutors",
        ...(heading === undefined ? {} : { heading }),
      }),
    )

  it("gives a stand-alone failure an sr-only h1", () => {
    const html = draw()
    expect(html.match(/<h1[ >]/g) ?? []).toHaveLength(1)
    expect(html).toMatch(/<h1 class="sr-only">Tutor profile<\/h1>/)
  })

  it("takes the screen's own name, or none where the screen already has an h1", () => {
    expect(draw("Book a session")).toMatch(/<h1 class="sr-only">Book a session<\/h1>/)
    expect(draw(false).match(/<h1[ >]/g) ?? []).toHaveLength(0)
  })

  it("the booking form, which sits under the screen's own h1, adds none", () => {
    const form = src("components/tutoring/booking-form.tsx")
    const use = /<TutorFailure[\s\S]*?\n\s*\/>/.exec(form)
    expect(use, "the form no longer draws TutorFailure").not.toBeNull()
    expect(use![0]).toContain("heading={false}")
  })

  it("the parent screens do not wrap it in a second h1", () => {
    expect(src("portals/parent/screens/tutoring/ParentFindTutor.tsx")).not.toMatch(/<h1 className="sr-only"/)
  })
})

// ── 6 · P-08: read-only, third person ──────────────────────────────────────

describe("P-08 · who the child shares progress with", () => {
  const draw = (id = "c1") => renderAt(`/parent/children/${id}/tutor-access`, "/parent/children/:childId/tutor-access", h(ChildTutorAccess))

  it("has no revoke control and no way to stop sharing", () => {
    mocks.grants = ok({ items: [grant("active", "g1"), grant("tutor_unavailable", "g2", tutorOf("t2", "Sami K."))] })
    mocks.log = ok({ items: [DETAIL, LIST], nextCursor: null })
    const html = draw()
    expect(html).not.toMatch(/<button[^>]*>[^<]*Stop sharing/)
    expect(words(html)).not.toContain("Stop sharing")
    expect(words(html)).not.toContain("Keep sharing")
    const code = src("portals/parent/screens/tutoring/ChildTutorAccess.tsx")
    expect(code).not.toMatch(/useRevokeTutorGrant|StopSharingSheet|stopSharingCopy|useRemoveTutoringBlock|useUpdateStudentTutoringSettings|canStop/)
  })

  it("says the SPEC's line about who decides", () => {
    expect(words(draw())).toContain(parentSharingLine("Maya R."))
  })

  it("lists the child's grants with the tutor, since and status, linking to the parent's tutor page", () => {
    mocks.grants = ok({ items: [grant("active")] })
    const html = draw()
    const text = words(html)
    expect(text).toContain("Nour A.")
    expect(text).toContain("Since")
    expect(text).toContain("Sharing")
    expect(hrefs(html)).toContain("/parent/tutors/t1?child=c1")
    expect(html).toContain('aria-label="Report Nour A."')
  })

  it("reads the log in the third person with the parent's tutor links", () => {
    mocks.log = ok({ items: [DETAIL, LIST], nextCursor: null })
    const html = draw()
    const text = words(html)
    expect(text).toContain("viewed Maya R.'s progress")
    expect(text).toContain("saw Maya R. in their student list")
    expect(hrefs(html)).toContain("/parent/tutors/t1")
    expect(hrefs(html).filter((href) => href.startsWith("/student"))).toEqual([])
    expect(text).not.toMatch(/\byour\b/i)
  })

  it("says so when there is nothing to show", () => {
    const text = words(draw())
    expect(text).toContain("Maya R. isn't sharing their progress with any tutor.")
    expect(text).toContain("No tutor has looked at Maya R.'s progress.")
  })

  it("reads each section's failure on its own, and asks the linked child's data only", () => {
    mocks.grants = failed(new ApiError(500, "boom"))
    mocks.log = pending()
    const text = words(draw())
    expect(text).toContain("We couldn't load who Maya R. shares with")
  })

  it("is a plain not-found for a child who is not on the linked list", () => {
    expect(words(draw("zzz"))).toContain("We couldn't find this child")
  })
})

describe("P-08 · a grant row, per status", () => {
  const statuses = Object.keys(GRANT_STATUS_VIEW) as GrantStatus[]

  it("covers every status the API can send, in the third person", () => {
    expect(statuses).toHaveLength(7)
    for (const status of statuses) {
      const row = parentGrantRowView(grant(status), "Maya R.", "c1")
      const said = `${row.status.label} ${row.status.detail} ${row.sinceLine}`
      expect(said, status).not.toMatch(/\b(you|your|you're)\b/i)
      expect(row.status.label, status).not.toBe("")
      expect(row.status.detail, status).not.toBe("")
      expect(Object.keys(row), status).not.toContain("canStop")
      expect(Object.keys(row), status).not.toContain("stopLabel")
      expect(row.tutorHref, status).toBe("/parent/tutors/t1?child=c1")
      expect(row.reportLabel, status).toBe("Report Nour A.")
    }
  })

  it("reads a tutor-side ending the same way whatever caused it", () => {
    const [a, b, c] = (["tutor_unavailable", "tutor_suspended", "tutor_closed"] as GrantStatus[]).map((s) =>
      parentGrantRowView(grant(s), "Maya R."),
    )
    expect(a.status).toEqual(b.status)
    expect(b.status).toEqual(c.status)
  })

  it("never names a block when the tutor's side ended the sharing", () => {
    for (const status of ["tutor_unavailable", "tutor_suspended", "tutor_closed"] as GrantStatus[]) {
      const { label, detail } = parentGrantRowView(grant(status), "Maya R.", "c1").status
      expect(label, status).not.toMatch(/block/i)
      expect(detail, status).not.toMatch(/block/i)
    }
  })

  it("names the child where the sentence is about what they did", () => {
    expect(parentGrantRowView(grant("revoked"), "Maya R.").status.label).toBe("Sharing stopped")
    expect(parentGrantRowView(grant("blocked"), "Maya R.").status.detail).toContain("Maya R.")
    expect(parentGrantRowView(grant("active"), "Maya R.").status.detail).toContain("Maya R.'s progress")
  })
})

// ── 7 · the SPEC's own sentences ───────────────────────────────────────────

describe("fixed copy matches the SPEC", () => {
  /** The first quoted string after `anchor` inside the parent screens' section. */
  function quoted(anchor: string): string {
    const at = PARENT_SPEC.indexOf(anchor)
    expect(at, `anchor not in SPEC §d Parent: ${anchor}`).toBeGreaterThan(-1)
    const open = PARENT_SPEC.indexOf('"', at + anchor.length)
    return PARENT_SPEC.slice(open + 1, PARENT_SPEC.indexOf('"', open + 1))
  }

  it("P-08's line about who decides", () => {
    const spec = quoted("No revoke control. Line:").replaceAll("{Child}", "Maya R.").replaceAll("{child}", "Maya R.")
    expect(parentSharingLine("Maya R.")).toBe(spec)
  })

  it("P-06's footnote under the read-only thread", () => {
    const spec = quoted("C-21 read-only (").replaceAll("{child}", "Maya R.")
    expect(parentNotesFootnote("Maya R.")).toBe(spec)
  })

  it("P-05's empty line and P-08's two empty lines", () => {
    const p05 = quoted("**States.** None:").replaceAll("{Child}", "Maya R.")
    expect(words(renderAt("/parent/children/c1/tutoring", "/parent/children/:childId/tutoring", h(ChildTutoring)))).toContain(p05)
    const grants = quoted("**States.** No grants:").replaceAll("{Child}", "Maya R.")
    const log = quoted("Empty log:").replaceAll("{child}", "Maya R.")
    const text = words(renderAt("/parent/children/c1/tutor-access", "/parent/children/:childId/tutor-access", h(ChildTutorAccess)))
    expect(text).toContain(grants)
    expect(text).toContain(log)
  })

  it("P-05's two links", () => {
    const section = PARENT_SPEC.slice(PARENT_SPEC.indexOf("**P-05"), PARENT_SPEC.indexOf("**P-06"))
    expect(section).toContain('"Who {child} shares progress with"')
    expect(section).toContain('"Find a tutor for {child}"')
  })
})

// ── 8 · the entry from the child's overview ────────────────────────────────

describe("the child's overview", () => {
  const overview = src("portals/parent/screens/ChildOverview.tsx")

  it("links to P-05 once, and keeps the headings the journey test reads", () => {
    expect(overview.match(/parentChildTutoringHref\(childId\)/g) ?? []).toHaveLength(1)
    expect(overview).toContain('from "@/lib/tutoring/parentTutoring"')
    for (const heading of ["Worth a conversation", "Subjects", "Recent papers", "Topics they're finding hard"]) {
      expect(overview, heading).toContain(heading)
    }
    expect(overview).toContain("{data.displayName}")
  })
})
