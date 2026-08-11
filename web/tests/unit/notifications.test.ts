import { describe, expect, it } from "vitest"
import { destinationFor, formatAge, typeLabel } from "@/portals/student/screens/Notifications"
import { answerPushContentRequest, buildPushReply } from "@/lib/push/pushClientBridge"
import { PUSH_CONTENT_REPLY } from "@/lib/push/pushDecision"
import type { Notification, NotificationsPage } from "@/lib/notificationTypes"

/*
 * G-13's inbox logic and the page half of the push handshake (P5.9 chunk B).
 *
 * The properties pinned here are the ones where the screen could mislead: a
 * link that cannot resolve, a relative age that drifts while the reader looks
 * at it, and a push that describes a notification the reader has already read.
 */

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    notificationId: "n1",
    type: "announcement",
    title: "Mock exam moved",
    body: "Now on the 14th.",
    payload: {},
    createdAt: "2026-08-10T09:00:00Z",
    readAt: null,
    ...overrides,
  }
}

describe("destinationFor", () => {
  it("links an announcement to the announcements screen", () => {
    expect(destinationFor(notification({ type: "announcement" }))).toBe("/student/announcements")
  })

  it("gives grade_ready NO link, because the only paper route cannot resolve an upload id", () => {
    // `/student/result/:paperId` addresses papers by history *index* and does
    // `int(paper_id)`, so a UUID 404s. A button here would be a dead link that
    // looks like a feature — the exact thing this build treats as worse than an
    // honest absence.
    expect(
      destinationFor(
        notification({ type: "grade_ready", payload: { uploadId: "0d1c8f2e-..." } }),
      ),
    ).toBeNull()
  })

  it.each(["streak_warning", "study_plan_reminder", "at_risk_alert"])(
    "gives %s no link, because it has no screen",
    (type) => {
      expect(destinationFor(notification({ type }))).toBeNull()
    },
  )
})

describe("typeLabel", () => {
  it("labels each of the five real types", () => {
    expect(typeLabel("grade_ready")).toBe("Marked")
    expect(typeLabel("at_risk_alert")).toBe("Needs attention")
  })

  it("renders an unknown type rather than hiding the row", () => {
    // An inbox that failed closed on one unrecognised type would hide every
    // notification beside it.
    expect(typeLabel("weekly_summary")).toBe("weekly_summary")
  })
})

describe("formatAge", () => {
  const now = new Date("2026-08-10T12:00:00Z")

  it.each([
    ["2026-08-10T09:00:00Z", "Today"],
    ["2026-08-09T09:00:00Z", "Yesterday"],
    ["2026-08-07T09:00:00Z", "3 days ago"],
    ["2026-08-02T09:00:00Z", "1 week ago"],
    ["2026-07-20T09:00:00Z", "3 weeks ago"],
  ])("renders %s as %s", (iso, expected) => {
    expect(formatAge(iso, now)).toBe(expected)
  })

  it("never renders an hour-precise age, so the number cannot drift while it is read", () => {
    // Two instants six hours apart on the same day must read identically.
    expect(formatAge("2026-08-10T01:00:00Z", now)).toBe(formatAge("2026-08-10T07:00:00Z", now))
  })

  it("returns an empty string for an unparseable date rather than 'NaN days ago'", () => {
    expect(formatAge("not a date", now)).toBe("")
  })

  it("treats a future timestamp as today rather than a negative age", () => {
    expect(formatAge("2026-08-11T09:00:00Z", now)).toBe("Today")
  })
})

describe("buildPushReply", () => {
  function page(notifications: Notification[]): NotificationsPage {
    return { notifications }
  }

  it("describes the newest UNREAD notification, not simply the newest", () => {
    // A push announces something new. Describing it with a row the reader has
    // already opened is actively misleading, and is what a naive
    // `notifications[0]` produces the moment a read row sits at the top.
    const reply = buildPushReply(
      page([
        notification({ notificationId: "read", title: "Old news", readAt: "2026-08-09T10:00:00Z" }),
        notification({ notificationId: "unread", title: "Mock exam moved", readAt: null }),
      ]),
    )
    expect(reply?.title).toBe("Mock exam moved")
    expect(reply?.type).toBe(PUSH_CONTENT_REPLY)
  })

  it("returns null when everything is already read", () => {
    const reply = buildPushReply(
      page([notification({ readAt: "2026-08-09T10:00:00Z" })]),
    )
    // The worker then shows its generic notification — honest, because this
    // page genuinely cannot say what the push was about.
    expect(reply).toBeNull()
  })

  it("returns null for an empty inbox and for a null page", () => {
    expect(buildPushReply(page([]))).toBeNull()
    expect(buildPushReply(null)).toBeNull()
  })

  it("carries a null body through rather than inventing one", () => {
    const reply = buildPushReply(page([notification({ body: null })]))
    expect(reply?.body).toBeNull()
  })

  it("routes a grade_ready push to the role-safe root, never to a dead paper link", () => {
    const reply = buildPushReply(
      page([notification({ type: "grade_ready", payload: { uploadId: "abc" } })]),
    )
    expect(reply?.url).toBe("/")
  })
})

describe("answerPushContentRequest", () => {
  it("returns the reply when the fetch succeeds", async () => {
    const reply = await answerPushContentRequest(async () => ({
      notifications: [notification({ title: "Mock exam moved" })],
    }))
    expect(reply?.title).toBe("Mock exam moved")
  })

  it("returns null instead of throwing when the fetch fails", async () => {
    // A push is not a moment with any UI to surface an error in, and the
    // worker's fallback already covers it. Throwing here would leave the
    // worker's port un-answered and burn its whole timeout.
    const reply = await answerPushContentRequest(() => Promise.reject(new Error("401")))
    expect(reply).toBeNull()
  })
})
