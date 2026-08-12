import { describe, expect, it } from "vitest"
import {
  daysLeftInWeek,
  formatWeekReset,
  monogram,
} from "@/portals/student/screens/Standings"
import {
  formatFriendsSince,
  requestOutcomeMessage,
} from "@/portals/student/screens/Friends"
import type { FriendRequest } from "@/lib/friendTypes"

/*
 * S-29 and S-30's pure logic (P5.8 chunk C).
 *
 * Everything pinned here is a place the screens could quietly state something
 * the backend never said: a reset boundary that moves overnight, a monogram
 * built from a name that has no letters, or "request sent" for a friendship
 * that was actually accepted on the spot.
 *
 * The board's *rendering* rules — a null streak showing nothing while a zero
 * shows "0" — are pinned on the wire instead, in
 * `tests/test_web_leaderboard.py`, because that is where the distinction can
 * actually be lost.
 */

describe("daysLeftInWeek", () => {
  it("counts whole civil days to the week's last day", () => {
    // Wednesday 5 Aug 2026 → Sunday 9 Aug 2026.
    expect(daysLeftInWeek("2026-08-09", new Date(2026, 7, 5))).toBe(4)
  })

  it("returns 0 on the final day itself", () => {
    expect(daysLeftInWeek("2026-08-09", new Date(2026, 7, 9))).toBe(0)
  })

  it("does not move across an evening", () => {
    // The whole reason this counts civil days rather than hours: a student
    // checking at 23:00 and again at 01:00 must not watch "4 days" become "3"
    // over one night when the reset is the same calendar distance away.
    const lateEvening = new Date(2026, 7, 5, 23, 30)
    const earlyMorning = new Date(2026, 7, 5, 1, 0)
    expect(daysLeftInWeek("2026-08-09", lateEvening)).toBe(
      daysLeftInWeek("2026-08-09", earlyMorning),
    )
  })

  it("goes negative for a week that has already ended", () => {
    // Surfaced rather than clamped: `formatWeekReset` decides the wording, and
    // a caller that wants to know the board is stale can still tell.
    expect(daysLeftInWeek("2026-08-09", new Date(2026, 7, 11))).toBe(-2)
  })
})

describe("formatWeekReset", () => {
  it("names today and tomorrow rather than counting them", () => {
    expect(formatWeekReset(0)).toBe("Resets today")
    expect(formatWeekReset(1)).toBe("Resets tomorrow")
  })

  it("counts days beyond tomorrow", () => {
    expect(formatWeekReset(4)).toBe("Resets in 4 days")
  })

  it("never renders a negative count", () => {
    // A stale board (the week already rolled over server-side) must not read
    // "Resets in -2 days"; it collapses into the honest "today".
    expect(formatWeekReset(-2)).toBe("Resets today")
  })
})

describe("monogram", () => {
  it("takes the first letter, upper-cased", () => {
    expect(monogram("ada lovelace")).toBe("A")
    expect(monogram("Bo")).toBe("B")
  })

  it("ignores leading whitespace", () => {
    expect(monogram("  Cleo")).toBe("C")
  })

  it("handles the anonymous placeholder", () => {
    // D5.5's fallback for a user who never set a display name. It is a real
    // word, so it monograms normally — there is no special case to get wrong.
    expect(monogram("Student")).toBe("S")
  })

  it("falls back to a neutral glyph for a name with no leading letter", () => {
    // Never an empty box and never a fabricated initial: a name that starts
    // with a digit, an emoji or nothing at all has no initial to show.
    expect(monogram("")).toBe("·")
    expect(monogram("42")).toBe("·")
    expect(monogram("   ")).toBe("·")
  })

  it("works for non-Latin scripts", () => {
    // The alphabet check is `\p{L}`, not `[A-Za-z]` — an Arabic display name
    // is normal in this product's launch market and must not degrade to "·".
    expect(monogram("ياسين")).toBe("ي")
  })
})

describe("requestOutcomeMessage", () => {
  function req(overrides: Partial<FriendRequest> = {}): FriendRequest {
    return {
      friendshipId: "f1",
      userId: "u1",
      displayName: "Ada",
      requestedAt: "2026-08-05T10:00:00Z",
      status: "pending",
      ...overrides,
    }
  }

  it("says a request was sent when it is still pending", () => {
    expect(requestOutcomeMessage(req())).toBe("Request sent to Ada.")
  })

  it("says you are already friends when the request crossed", () => {
    // The load-bearing case (D5.6 §2): when both parties had already asked,
    // the backend accepts the friendship outright. Telling that student
    // "request sent" would leave them waiting for something already done.
    expect(requestOutcomeMessage(req({ status: "accepted" }))).toBe(
      "You and Ada are now friends — they had already asked.",
    )
  })

  it("reads the response's status rather than assuming success means pending", () => {
    const pending = requestOutcomeMessage(req({ status: "pending" }))
    const accepted = requestOutcomeMessage(req({ status: "accepted" }))
    expect(pending).not.toBe(accepted)
  })
})

describe("formatFriendsSince", () => {
  it("formats an accepted friendship's date", () => {
    expect(formatFriendsSince("2026-08-05T10:00:00Z")).toBe("Aug 2026")
  })

  it("passes null through rather than inventing a date", () => {
    // `responded_at` is nullable on the model. "Friends since —" or a
    // defaulted today would both be claims the row does not make.
    expect(formatFriendsSince(null)).toBeNull()
  })
})
