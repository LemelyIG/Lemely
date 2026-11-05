import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import {
  NOTIFICATION_TOGGLES,
  apiTimeValue,
  quietHoursSummary,
  quietHoursUpdate,
  timeInputValue,
  visibleToggles,
  type NotificationPreferences,
} from "@/lib/notificationPrefs"
import {
  resolvePushState,
  subscribePayloadFrom,
  urlBase64ToUint8Array,
} from "@/lib/push/pushEnable"

/*
 * G-12's decision logic (P5.9 chunk C).
 *
 * The screen itself is not mountable here — `vitest.config.ts:25` is
 * `environment: "node"` with no jsdom — so everything worth pinning was written
 * as a pure function outside it. What these tests defend is the same thing in
 * four different places: **a settings screen must never claim a state it is not
 * in.** A toggle that says "on" for something switched off, a quiet-hours window
 * silently half-saved, a push button offered by a server that has no keys, or a
 * subscription posted without the key needed to encrypt to it — each of those is
 * a lie told by a control the reader trusts.
 */

/** The members of the backend's `NotificationType` enum, read from its source. */
function backendNotificationTypes(): string[] {
  const source = readFileSync(
    path.resolve(__dirname, "../../../lemely/db/models/enums.py"),
    "utf-8",
  )
  const block = /class NotificationType\(enum\.Enum\):([\s\S]*?)\n\n\nclass /.exec(source)
  if (block === null) throw new Error("NotificationType not found in enums.py")
  return [...block[1].matchAll(/^ {4}([a-z_]+) = "[a-z_]+"$/gm)].map((m) => m[1])
}

function camelCase(snake: string): string {
  return snake.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
}

const TUTORING_KEYS = [
  "bookingRequest",
  "bookingUpdate",
  "bookingNote",
  "tutorAccess",
  "tutorReview",
  "tutorListing",
  "parentLink",
  "tutoringReport",
] as const

describe("NOTIFICATION_TOGGLES", () => {
  it("ships one toggle per backend notification type (fourteen) and no weekly summary", () => {
    // UI spec §G-12 lists a "weekly summary". `NotificationType` has no member,
    // column, sender or row for it — a switch for it would gate nothing, which is
    // what UI spec §1.4 forbids. The expected keys are derived from the backend
    // enum's source, so a fifteenth type there fails this until it gets a switch.
    const backend = backendNotificationTypes()
    expect(backend).toHaveLength(14) // non-vacuity: 6 original + 8 tutoring
    expect(NOTIFICATION_TOGGLES.map((toggle) => toggle.key)).toEqual(backend.map(camelCase))
    expect(JSON.stringify(NOTIFICATION_TOGGLES).toLowerCase()).not.toContain("weekly")
  })

  it("keeps the original six first, in their original order, then the eight tutoring ones", () => {
    expect(NOTIFICATION_TOGGLES.slice(0, 6).map((toggle) => toggle.key)).toEqual([
      "gradeReady",
      "announcement",
      "streakWarning",
      "studyPlanReminder",
      "atRiskAlert",
      "reviewWithdrawn",
    ])
    expect(NOTIFICATION_TOGGLES.slice(6).map((toggle) => toggle.key)).toEqual([...TUTORING_KEYS])
  })

  it("leaves tutoring role gating to the server's null, not to a client-side role flag", () => {
    for (const key of TUTORING_KEYS) {
      expect(NOTIFICATION_TOGGLES.find((toggle) => toggle.key === key)?.role).toBeUndefined()
    }
  })

  it("keeps tutoring copy clear of the words the tutoring copy rule bans", () => {
    for (const key of TUTORING_KEYS) {
      const toggle = NOTIFICATION_TOGGLES.find((t) => t.key === key)
      const text = `${toggle?.label} ${toggle?.description}`.toLowerCase()
      expect(text).not.toContain("improvement")
      expect(text).not.toContain("verified")
      expect(text).not.toContain("!")
      expect(text).not.toContain("—")
    }
  })

  it("gates reviewWithdrawn to the teacher role, the only role it ever fires for", () => {
    const toggle = NOTIFICATION_TOGGLES.find((t) => t.key === "reviewWithdrawn")
    expect(toggle?.role).toBe("teacher")
    expect(NOTIFICATION_TOGGLES.filter((t) => t.role === "teacher")).toHaveLength(1)
  })

  it("gives every toggle a description, so none ships as a bare unexplained switch", () => {
    for (const toggle of NOTIFICATION_TOGGLES) {
      expect(toggle.label.length).toBeGreaterThan(0)
      expect(toggle.description.length).toBeGreaterThan(0)
    }
  })
})

/** What `GET /api/me/notification-preferences` returns, with every role-gated value null. */
function prefs(overrides: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    gradeReady: true,
    announcement: true,
    streakWarning: true,
    studyPlanReminder: true,
    atRiskAlert: null,
    reviewWithdrawn: null,
    bookingRequest: null,
    bookingUpdate: null,
    bookingNote: null,
    tutorAccess: null,
    tutorReview: null,
    tutorListing: null,
    parentLink: null,
    tutoringReport: null,
    quietHoursStart: null,
    quietHoursEnd: null,
    ...overrides,
  }
}

const keysOf = (toggles: readonly { key: string }[]): string[] => toggles.map((t) => t.key)

describe("visibleToggles", () => {
  it("hides every toggle whose GET value is null", () => {
    // A student: the server nulls the gated ones, and the screen must not offer a
    // switch the router would answer with a 422.
    const student = prefs({ bookingUpdate: true, bookingNote: true, tutorAccess: true, tutorReview: false })
    expect(keysOf(visibleToggles(student))).toEqual([
      "gradeReady",
      "announcement",
      "streakWarning",
      "studyPlanReminder",
      "bookingUpdate",
      "bookingNote",
      "tutorAccess",
      "tutorReview",
    ])
  })

  it("shows a toggle that is false: off is a state, null is absence", () => {
    const shown = visibleToggles(prefs({ tutoringReport: false }))
    expect(keysOf(shown)).toContain("tutoringReport")
  })

  it("renders a tutoring toggle only when its value is non-null, for every one of the eight", () => {
    for (const key of TUTORING_KEYS) {
      expect(keysOf(visibleToggles(prefs()))).not.toContain(key)
      expect(keysOf(visibleToggles(prefs({ [key]: true })))).toContain(key)
    }
  })

  it("gives each role exactly the toggles the server enabled for it", () => {
    const teacher = prefs({
      atRiskAlert: true,
      reviewWithdrawn: true,
      bookingRequest: true,
      bookingUpdate: true,
      bookingNote: true,
      tutorAccess: true,
      tutorReview: true,
      tutorListing: true,
    })
    const parent = prefs({ atRiskAlert: true, bookingUpdate: true, bookingNote: true, tutorAccess: true, parentLink: true })
    const admin = prefs({ tutoringReport: true })
    expect(keysOf(visibleToggles(teacher, { showTeacherOnly: true }))).toEqual([
      "gradeReady",
      "announcement",
      "streakWarning",
      "studyPlanReminder",
      "atRiskAlert",
      "reviewWithdrawn",
      "bookingRequest",
      "bookingUpdate",
      "bookingNote",
      "tutorAccess",
      "tutorReview",
      "tutorListing",
    ])
    expect(keysOf(visibleToggles(parent))).toEqual([
      "gradeReady",
      "announcement",
      "streakWarning",
      "studyPlanReminder",
      "atRiskAlert",
      "bookingUpdate",
      "bookingNote",
      "tutorAccess",
      "parentLink",
    ])
    expect(keysOf(visibleToggles(admin)).slice(-1)).toEqual(["tutoringReport"])
  })

  it("keeps showTeacherOnly gating reviewWithdrawn, as before", () => {
    const teacher = prefs({ reviewWithdrawn: true })
    expect(keysOf(visibleToggles(teacher))).not.toContain("reviewWithdrawn")
    expect(keysOf(visibleToggles(teacher, { showTeacherOnly: false }))).not.toContain("reviewWithdrawn")
    expect(keysOf(visibleToggles(teacher, { showTeacherOnly: true }))).toContain("reviewWithdrawn")
  })

  it("never lets showTeacherOnly reveal a toggle the server nulled", () => {
    expect(keysOf(visibleToggles(prefs(), { showTeacherOnly: true }))).toEqual([
      "gradeReady",
      "announcement",
      "streakWarning",
      "studyPlanReminder",
    ])
  })
})

describe("timeInputValue", () => {
  it("narrows a pydantic time to what a time input accepts", () => {
    expect(timeInputValue("22:00:00")).toBe("22:00")
    expect(timeInputValue("07:30:00.000000")).toBe("07:30")
    expect(timeInputValue("07:30")).toBe("07:30")
  })

  it("renders no quiet hours as an empty field rather than a made-up time", () => {
    expect(timeInputValue(null)).toBe("")
  })

  it("blanks an unparseable value instead of passing it through", () => {
    // A time input silently rejects what it cannot parse and shows blank, so
    // passing the raw string through would leave React's value and the DOM's
    // permanently out of step — the field would look empty and refuse to clear.
    expect(timeInputValue("half past ten")).toBe("")
  })
})

describe("apiTimeValue", () => {
  it("normalises to seconds precision, the shape the server echoes back", () => {
    expect(apiTimeValue("22:00")).toBe("22:00:00")
    expect(apiTimeValue("22:00:30")).toBe("22:00:30")
  })

  it("maps an empty field to an explicit null, which is how the API clears a bound", () => {
    expect(apiTimeValue("")).toBeNull()
  })
})

describe("quietHoursUpdate", () => {
  it("sends both bounds together", () => {
    expect(quietHoursUpdate("22:00", "07:00")).toEqual({
      ok: true,
      update: { quietHoursStart: "22:00:00", quietHoursEnd: "07:00:00" },
    })
  })

  it("clears both bounds together", () => {
    expect(quietHoursUpdate("", "")).toEqual({
      ok: true,
      update: { quietHoursStart: null, quietHoursEnd: null },
    })
  })

  it("refuses exactly one bound, in either direction, before the server 422s", () => {
    // `NotificationPreferencesService.set` raises on a merged result with one
    // bound set and the router turns that into a 422. Catching it here is not
    // duplication: without it a reader who types a start time and tabs away is
    // shown a server error for a form they have not finished filling in.
    const startOnly = quietHoursUpdate("22:00", "")
    const endOnly = quietHoursUpdate("", "07:00")
    expect(startOnly.ok).toBe(false)
    expect(endOnly.ok).toBe(false)
    if (!startOnly.ok) expect(startOnly.message).toContain("both")
  })

  it("does not invent a rule the backend does not have", () => {
    // Start equal to end is accepted server-side. A stricter client would
    // reject input the server would have stored, which is the same class of
    // dishonesty as the reverse.
    expect(quietHoursUpdate("22:00", "22:00").ok).toBe(true)
  })
})

describe("quietHoursSummary", () => {
  it("says out loud that an overnight window wraps past midnight", () => {
    // "22:00 to 07:00" read literally is an empty range. Without this line a
    // reader has no way to check we understood them short of waiting until 2am.
    expect(quietHoursSummary("22:00:00", "07:00:00")).toContain("next morning")
  })

  it("does not claim a wrap for a same-day window", () => {
    expect(quietHoursSummary("09:00:00", "17:00:00")).not.toContain("next morning")
  })

  it("says nothing at all when quiet hours are unset", () => {
    expect(quietHoursSummary(null, null)).toBeNull()
    expect(quietHoursSummary("22:00:00", null)).toBeNull()
  })
})

describe("resolvePushState", () => {
  const base = {
    supported: true,
    available: true,
    permission: "granted",
    subscribed: true,
  } as const

  it("reports enabled only when the browser holds a subscription", () => {
    expect(resolvePushState(base)).toEqual({ kind: "enabled" })
  })

  it("reports prompt, not enabled, when permission is granted but the subscription is gone", () => {
    // The permission is the browser's memory of an old answer; the subscription
    // is what the server can actually push to. Cleared site data, a new profile
    // or a 410 the server acted on leaves the first without the second, and
    // showing "on" there is the exact lie this screen exists to prevent.
    expect(resolvePushState({ ...base, subscribed: false })).toEqual({ kind: "prompt" })
  })

  it("reports denied distinctly from unavailable", () => {
    // UI spec §G-12 asks for these two to be shown differently: one is the
    // reader's to fix, the other is a fact about the deployment.
    expect(resolvePushState({ ...base, permission: "denied" })).toEqual({ kind: "denied" })
  })

  it("reports the deployment's missing keys as unavailable, not as an error state", () => {
    // D5.9 §4: this build ships with no VAPID keys, so `available: false` is the
    // designed answer and is the state every current build of this repo shows.
    expect(resolvePushState({ ...base, available: false })).toEqual({ kind: "unavailable" })
  })

  it("puts server unavailability ahead of browser support, because it binds harder", () => {
    // Both mean "push cannot happen". Only the browser one looks actionable —
    // and acting on it achieves nothing while the server has no keys to sign
    // with, so telling the reader to switch browsers would be an errand that
    // ends in the same place.
    expect(resolvePushState({ ...base, available: false, supported: false })).toEqual({
      kind: "unavailable",
    })
    expect(resolvePushState({ ...base, supported: false })).toEqual({ kind: "unsupported" })
  })

  it("never reports enabled for a browser that cannot do push", () => {
    for (const permission of ["default", "granted", "denied"] as const) {
      const state = resolvePushState({ ...base, supported: false, permission })
      expect(state.kind).not.toBe("enabled")
    }
  })
})

describe("urlBase64ToUint8Array", () => {
  it("decodes base64url, including the two characters standard base64 does not have", () => {
    // A VAPID key is base64url (RFC 8292) and `atob` speaks only standard
    // base64: without the substitutions a real key either decodes to different
    // bytes or throws, and the push service rejects the subscription with an
    // error that says nothing about why.
    const standard = "++//"
    const urlSafe = "--__"
    expect(Array.from(urlBase64ToUint8Array(urlSafe))).toEqual(
      Array.from(urlBase64ToUint8Array(standard)),
    )
  })

  it("re-pads an unpadded key", () => {
    // Base64url as specified carries no `=` padding, and `atob` requires it.
    expect(Array.from(urlBase64ToUint8Array("QQ"))).toEqual([65])
    expect(Array.from(urlBase64ToUint8Array("QUJD"))).toEqual([65, 66, 67])
  })

  it("produces the 65 bytes an uncompressed P-256 point occupies", () => {
    // The shape a real applicationServerKey has: 0x04 followed by two 32-byte
    // coordinates. A length that is not 65 means the key was mangled, and the
    // failure would otherwise surface only as a rejected subscription.
    const key = "B" + "A".repeat(85) + "w"
    expect(urlBase64ToUint8Array(key).length).toBe(65)
  })
})

describe("subscribePayloadFrom", () => {
  const full = {
    endpoint: "https://push.example/abc",
    keys: { p256dh: "p", auth: "a" },
    expirationTime: null,
  }

  it("keeps only the three fields the subscribe route wants", () => {
    expect(subscribePayloadFrom(full)).toEqual({
      endpoint: "https://push.example/abc",
      keys: { p256dh: "p", auth: "a" },
    })
  })

  it("refuses a subscription missing either key", () => {
    // The browser types both keys as optional and on some engines they really
    // are absent. Posting the partial row would have the server store something
    // it can never encrypt to, and this screen would then honestly report push
    // as enabled while every send silently failed.
    expect(subscribePayloadFrom({ ...full, keys: { auth: "a" } })).toBeNull()
    expect(subscribePayloadFrom({ ...full, keys: { p256dh: "p" } })).toBeNull()
    expect(subscribePayloadFrom({ ...full, keys: { p256dh: "", auth: "a" } })).toBeNull()
  })

  it("refuses anything that is not a subscription at all", () => {
    expect(subscribePayloadFrom(null)).toBeNull()
    expect(subscribePayloadFrom("https://push.example/abc")).toBeNull()
    expect(subscribePayloadFrom({ endpoint: "", keys: { p256dh: "p", auth: "a" } })).toBeNull()
    expect(subscribePayloadFrom({ endpoint: "https://push.example/abc" })).toBeNull()
  })
})
