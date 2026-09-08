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
