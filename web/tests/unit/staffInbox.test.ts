import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import {
  PARENT_INBOX_EMPTY,
  STAFF_INBOX_ERROR,
  TEACHER_INBOX_EMPTY,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
  unreadBadgeLabel,
  unreadCountOf,
} from "@/lib/staffInbox"
import type { Notification, NotificationsPage } from "@/lib/notificationTypes"

/*
 * The teacher and parent inboxes (push-delivery spec §6). Only `at_risk_alert`
 * ever reaches these two roles, and the same alert reads differently to each:
 * a teacher sees a student they teach, a parent sees their own child.
 *
 * The runner has no DOM, so the screens' five states are pinned two ways: the
 * decisions as pure functions here, and the wiring of `QueryState`'s slots as
 * a source-text check below. Playwright renders the real screens.
 */

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    notificationId: "n1",
    type: "at_risk_alert",
    title: "Amira may need support",
    body: "Declining trend",
    payload: { studentId: "stu-1", reason: "declining_trend" },
    createdAt: "2026-09-05T09:00:00Z",
    readAt: null,
    ...overrides,
  }
}

const page = (rows: Notification[]): NotificationsPage => ({ notifications: rows })

describe("staffDestinationFor", () => {
  it("sends a teacher to the student's page", () => {
    expect(staffDestinationFor("teacher", notification())).toBe("/teacher/students/stu-1")
  })

  it("sends a parent to the child's page", () => {
    expect(staffDestinationFor("parent", notification())).toBe("/parent/children/stu-1")
  })

  it("has no destination without a studentId, rather than a broken link", () => {
    expect(staffDestinationFor("teacher", notification({ payload: {} }))).toBeNull()
  })

  it("has no destination for a type these roles do not receive", () => {
    expect(staffDestinationFor("parent", notification({ type: "announcement" }))).toBeNull()
  })

  it("encodes the id", () => {
    expect(staffDestinationFor("teacher", notification({ payload: { studentId: "a b" } }))).toBe(
      "/teacher/students/a%20b",
    )
  })
})

describe("the four states", () => {
  it("is empty only with no rows", () => {
    expect(isInboxEmpty(page([]))).toBe(true)
    expect(isInboxEmpty(page([notification()]))).toBe(false)
  })

  it("counts unread rows, not rows", () => {
    expect(
      unreadCountOf(page([notification(), notification({ readAt: "2026-09-05T10:00:00Z" })])),
    ).toBe(1)
  })

  it("offers mark-all-read only while something is unread", () => {
    expect(showMarkAllRead(page([notification()]))).toBe(true)
    expect(showMarkAllRead(page([notification({ readAt: "2026-09-05T10:00:00Z" })]))).toBe(false)
    expect(showMarkAllRead(page([]))).toBe(false)
  })

  it("words the empty state for each role, and the error state once for both", () => {
    expect(TEACHER_INBOX_EMPTY.body).toContain("a student you teach")
    expect(PARENT_INBOX_EMPTY.body).toContain("your child")
    expect(STAFF_INBOX_ERROR.heading).toBe("Notifications could not be loaded")
  })
})

describe("unreadBadgeLabel", () => {
  it("is absent at zero, pending, or error", () => {
    expect(unreadBadgeLabel(undefined)).toBeNull()
    expect(unreadBadgeLabel({ unread: 0, total: 3, unreadByType: {} })).toBeNull()
  })

  it("shows the count, capped so the sidebar never widens", () => {
    expect(unreadBadgeLabel({ unread: 4, total: 9, unreadByType: {} })).toBe("4")
    expect(unreadBadgeLabel({ unread: 120, total: 120, unreadByType: {} })).toBe("99+")
  })
})

describe("staffTypeLabel", () => {
  it("labels the one type these inboxes receive, and never hides an unknown one", () => {
    expect(staffTypeLabel("at_risk_alert")).toBe("Needs attention")
    expect(staffTypeLabel("weekly_summary")).toBe("weekly_summary")
  })

  /* Task 9/17 (D10): a teacher's inbox is where review_withdrawn actually
   * lands (student-triggered deletion), so it must not fall back to the
   * raw enum string the way an unknown type does. */
  it("labels review_withdrawn, teacher-only unlike at_risk_alert above", () => {
    expect(staffTypeLabel("review_withdrawn")).toBe("Review withdrawn")
  })
})

/* The eight tutoring types (SPEC section b.4). A teacher is a tutor, so the tutor-side notices
 * land in the teacher inbox; a parent gets the family-side ones. The payload holds ids only. */
describe("tutoring notices in the staff inboxes", () => {
  const BOOKING = "b-1"

  it("labels all eight tutoring types, none falling back to the raw enum name", () => {
    const labels = {
      booking_request: "Session request",
      booking_update: "Session update",
      booking_note: "Session note",
      tutor_access: "Progress sharing",
      tutor_review: "Review decision",
      tutor_listing: "Tutor profile",
      parent_link: "Parent link",
      tutoring_report: "Safety report",
    }
    expect(Object.keys(labels)).toHaveLength(8)
    for (const [type, label] of Object.entries(labels)) {
      expect(staffTypeLabel(type)).toBe(label)
    }
  })

  it("sends a tutor to the session for a request, an update or a note", () => {
    for (const type of ["booking_request", "booking_update", "booking_note"]) {
      expect(
        staffDestinationFor("teacher", notification({ type, payload: { bookingId: BOOKING } })),
      ).toBe(`/teacher/tutoring/sessions/${BOOKING}`)
    }
  })

  it("sends a parent to the child's session, which needs both ids", () => {
    const payload = { bookingId: BOOKING, studentId: "stu-1" }
    for (const type of ["booking_update", "booking_note"]) {
      expect(staffDestinationFor("parent", notification({ type, payload }))).toBe(
        "/parent/children/stu-1/sessions/b-1",
      )
    }
    expect(
      staffDestinationFor(
        "parent",
        notification({ type: "booking_update", payload: { bookingId: BOOKING } }),
      ),
    ).toBeNull()
  })

  it("routes progress-sharing notices to where each role sees them", () => {
    expect(staffDestinationFor("teacher", notification({ type: "tutor_access", payload: { grantId: "g" } }))).toBe(
      "/teacher/tutoring/students",
    )
    expect(
      staffDestinationFor(
        "parent",
        notification({ type: "tutor_access", payload: { grantId: "g", studentId: "stu-1" } }),
      ),
    ).toBe("/parent/children/stu-1/tutor-access")
    // A class-join notice is about tutoring, not about a grant.
    expect(
      staffDestinationFor(
        "parent",
        notification({ type: "tutor_access", payload: { enrollmentId: "e", studentId: "stu-1" } }),
      ),
    ).toBe("/parent/children/stu-1/tutoring")
  })

  it("routes listing and review decisions to the tutor's own screens", () => {
    expect(
      staffDestinationFor("teacher", notification({ type: "tutor_listing", payload: { approvalEventId: "a" } })),
    ).toBe("/teacher/tutoring/profile")
    expect(
      staffDestinationFor("teacher", notification({ type: "tutor_review", payload: { replyId: "r" } })),
    ).toBe("/teacher/tutoring/preview")
  })

  it("sends a parent-link notice to the parent's children list", () => {
    expect(
      staffDestinationFor("parent", notification({ type: "parent_link", payload: { eventId: "e" } })),
    ).toBe("/parent")
  })

  it("gives a role no link into a screen it cannot open", () => {
    const payload = { bookingId: BOOKING, studentId: "stu-1", grantId: "g", approvalEventId: "a" }
    expect(staffDestinationFor("parent", notification({ type: "booking_request", payload }))).toBeNull()
    expect(staffDestinationFor("parent", notification({ type: "tutor_listing", payload }))).toBeNull()
    expect(staffDestinationFor("teacher", notification({ type: "parent_link", payload }))).toBeNull()
    expect(staffDestinationFor("teacher", notification({ type: "tutoring_report", payload }))).toBeNull()
  })

  it("encodes every id it splices into a path", () => {
    expect(
      staffDestinationFor(
        "parent",
        notification({ type: "booking_update", payload: { bookingId: "a/b", studentId: "c d" } }),
      ),
    ).toBe("/parent/children/c%20d/sessions/a%2Fb")
  })
})

describe("both screens wire the four states and mark-all-read", () => {
  const screens = {
    teacher: "../../src/portals/teacher/screens/Notifications.tsx",
    parent: "../../src/portals/parent/screens/Notifications.tsx",
  }

  it.each(Object.entries(screens))("%s", (_name, relative) => {
    const source = readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8")
    // Loading, error, empty, loaded: the four slots of QueryState.
    expect(source).toMatch(/skeleton=\{<ListSkeleton/)
    expect(source).toMatch(/error=\{STAFF_INBOX_ERROR\}/)
    expect(source).toMatch(/isEmpty=\{isInboxEmpty\}/)
    expect(source).toMatch(/empty=\{<EmptyState/)
    // Mark all as read, gated on there being something unread.
    expect(source).toContain("useMarkAllNotificationsRead()")
    expect(source).toContain("showMarkAllRead(data)")
    // Rows link through the role-aware destination, never a hardcoded path.
    expect(source).toContain("staffDestinationFor(")
  })
})
