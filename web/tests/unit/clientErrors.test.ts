import { describe, expect, it } from "vitest"
import {
  buildClientErrorReport,
  redactRoute,
  ReportThrottle,
  type ClientErrorReport,
} from "@/lib/clientErrors"

/*
 * PR 1B (client error reporting), pinned.
 *
 * `reportClientError` itself — the side-effecting `fetch` call — is
 * deliberately not exercised here: it reads `window`/`navigator`/`Date.now`
 * directly, and this suite runs under Node with no DOM (`vitest.config.ts`,
 * D3.20). Everything worth pinning is reachable through the two pure pieces
 * it is built from, `buildClientErrorReport` and `ReportThrottle`, which is
 * exactly why the module is split that way — see `clientErrors.ts`'s own
 * doc comment.
 */

const NOW = new Date(Date.UTC(2026, 8, 2, 12, 0, 0))

function baseInput(overrides: Partial<Parameters<typeof buildClientErrorReport>[0]> = {}) {
  return {
    error: new Error("boom"),
    kind: "render" as const,
    componentStack: null,
    route: "/student/board",
    buildId: "abc123",
    userAgent: "test-agent/1.0",
    now: NOW,
    ...overrides,
  }
}

describe("buildClientErrorReport", () => {
  it("reads message and stack from a real Error", () => {
    const error = new Error("subject fetch failed")
    const report = buildClientErrorReport(baseInput({ error }))
    expect(report.message).toBe("subject fetch failed")
    expect(report.stack).toBe(error.stack)
  })

  it.each([
    ["a string", "plain string throw"],
    ["a number", 42],
    ["a plain object", { code: "E_BAD" }],
    ["undefined", undefined],
    ["null", null],
  ])("stringifies a non-Error throwable (%s) and reports no stack", (_label, thrown) => {
    const report = buildClientErrorReport(baseInput({ error: thrown }))
    expect(report.message).toBe(String(thrown))
    expect(report.stack).toBeNull()
  })

  describe("describeThrown defensiveness (only reachable through buildClientErrorReport, since describeThrown itself is not exported)", () => {
    it("falls back to a literal message for a null-prototype throwable (String() throws on it)", () => {
      // Object.create(null) has no inherited toString/valueOf, so
      // String(x) throws TypeError("Cannot convert object to primitive
      // value") rather than producing "[object Object]".
      const bad = Object.create(null) as unknown
      const report = buildClientErrorReport(baseInput({ error: bad }))
      expect(report.message).toBe("Unreportable error")
      expect(report.stack).toBeNull()
    })

    it("falls back to a literal message when a thrown object's own toString throws", () => {
      const bad = {
        toString() {
          throw new Error("toString exploded")
        },
      }
      const report = buildClientErrorReport(baseInput({ error: bad }))
      expect(report.message).toBe("Unreportable error")
      expect(report.stack).toBeNull()
    })

    it("falls back to a literal message when an Error's message getter throws", () => {
      const bad = new Error("irrelevant, the getter below wins")
      Object.defineProperty(bad, "message", {
        get() {
          throw new Error("message getter exploded")
        },
      })
      const report = buildClientErrorReport(baseInput({ error: bad }))
      expect(report.message).toBe("Unreportable error")
    })

    it("falls back to a null stack when an Error's stack getter throws", () => {
      const bad = new Error("boom")
      Object.defineProperty(bad, "stack", {
        get() {
          throw new Error("stack getter exploded")
        },
      })
      const report = buildClientErrorReport(baseInput({ error: bad }))
      expect(report.message).toBe("boom")
      expect(report.stack).toBeNull()
    })

    it("maps an empty Error message to the literal 'Unknown error', not an empty string", () => {
      // The backend DTO for POST /api/client-errors requires min_length=1
      // on message.
      const report = buildClientErrorReport(baseInput({ error: new Error("") }))
      expect(report.message).toBe("Unknown error")
    })

    it("maps a thrown empty string to 'Unknown error' the same way", () => {
      const report = buildClientErrorReport(baseInput({ error: "" }))
      expect(report.message).toBe("Unknown error")
    })
  })

  it("passes the buildId straight through untouched when under the limit", () => {
    const report = buildClientErrorReport(baseInput({ buildId: "a1b2c3d4e5f6" }))
    expect(report.buildId).toBe("a1b2c3d4e5f6")
  })

  it("passes componentStack through when the caller supplies one", () => {
    const report = buildClientErrorReport(
      baseInput({ componentStack: "\n    at Widget\n    at StudentLayout" }),
    )
    expect(report.componentStack).toBe("\n    at Widget\n    at StudentLayout")
  })

  it("reports componentStack as null when the caller omits it", () => {
    const report = buildClientErrorReport(baseInput({ componentStack: undefined }))
    expect(report.componentStack).toBeNull()
  })

  it("stamps occurredAt as the injected clock's ISO string, never the real clock", () => {
    const report = buildClientErrorReport(baseInput())
    expect(report.occurredAt).toBe(NOW.toISOString())
  })

  it("carries the kind straight through", () => {
    expect(buildClientErrorReport(baseInput({ kind: "unhandled" })).kind).toBe("unhandled")
    expect(buildClientErrorReport(baseInput({ kind: "rejection" })).kind).toBe("rejection")
  })

  it("reports userAgent as null when the caller has none", () => {
    const report = buildClientErrorReport(baseInput({ userAgent: null }))
    expect(report.userAgent).toBeNull()
  })

  describe("truncation, one field and exactly one limit past it at a time", () => {
    it("truncates message at 2000 chars", () => {
      const long = "x".repeat(2500)
      const report = buildClientErrorReport(baseInput({ error: new Error(long) }))
      expect(report.message).toHaveLength(2000)
      expect(report.message).toBe(long.slice(0, 2000))
    })

    it("leaves a message under the limit untouched", () => {
      const short = "y".repeat(50)
      const report = buildClientErrorReport(baseInput({ error: new Error(short) }))
      expect(report.message).toBe(short)
    })

    it("truncates stack at 8000 chars", () => {
      const error = new Error("boom")
      error.stack = "s".repeat(9000)
      const report = buildClientErrorReport(baseInput({ error }))
      expect(report.stack).toHaveLength(8000)
    })

    it("truncates componentStack at 8000 chars", () => {
      const report = buildClientErrorReport(baseInput({ componentStack: "c".repeat(8500) }))
      expect(report.componentStack).toHaveLength(8000)
    })

    it("drops a surrogate pair whole rather than splitting it when the cut lands inside one", () => {
      // MESSAGE_LIMIT is 2000. An astral character (most emoji included) is
      // two UTF-16 code units — a surrogate pair — so 1999 plain chars plus
      // one such emoji puts the 2000th code unit exactly on the emoji's
      // leading (high) surrogate. `String#slice(0, 2000)` alone would keep
      // that lone high surrogate with no low surrogate to follow it: legal
      // enough to survive `JSON.stringify`, but not valid UTF-8, which is
      // what turns into a raise on the structlog side of this report.
      const emoji = "\u{1F600}" // 😀 — codePointAt(0) === 0x1f600, a real pair
      const message = "x".repeat(1999) + emoji
      expect(message).toHaveLength(2001) // sanity check on the setup itself

      const report = buildClientErrorReport(baseInput({ error: new Error(message) }))

      expect(report.message).toBe("x".repeat(1999))
      expect(report.message).toHaveLength(1999)
      const lastUnit = report.message.charCodeAt(report.message.length - 1)
      expect(lastUnit < 0xd800 || lastUnit > 0xdbff).toBe(true)
    })

    it("keeps a surrogate pair whole when the cut lands cleanly after it", () => {
      // The same emoji, one character earlier, so the pair sits entirely
      // inside the limit — nothing here should be touched by the guard.
      const emoji = "\u{1F600}"
      const message = "x".repeat(1998) + emoji // 2000 code units exactly
      const report = buildClientErrorReport(baseInput({ error: new Error(message) }))
      expect(report.message).toBe(message)
      expect(report.message).toHaveLength(2000)
    })

    it("truncates route at 500 chars, after redaction", () => {
      // Many short segments (none reaching the 20-char opaque-segment
      // threshold below) rather than one long one, so this pins truncation
      // alone without the path-redaction rules in the "route redaction"
      // block below also firing on the same string.
      const longRoute = `/student/board?extra=${"seg/".repeat(150)}`
      const report = buildClientErrorReport(baseInput({ route: longRoute }))
      expect(report.route).toHaveLength(500)
      expect(report.route).toBe(longRoute.slice(0, 500))
    })

    it("truncates buildId at 64 chars", () => {
      const report = buildClientErrorReport(baseInput({ buildId: "b".repeat(100) }))
      expect(report.buildId).toHaveLength(64)
    })

    it("truncates userAgent at 500 chars", () => {
      const report = buildClientErrorReport(baseInput({ userAgent: "u".repeat(700) }))
      expect(report.userAgent).toHaveLength(500)
    })
  })

  describe("route redaction", () => {
    it("leaves a route with no query string untouched", () => {
      expect(redactRoute("/student/board")).toBe("/student/board")
    })

    it("leaves an unrelated query untouched", () => {
      expect(redactRoute("/teacher/students?page=2&sort=name")).toBe(
        "/teacher/students?page=2&sort=name",
      )
    })

    it.each(["token", "code", "access_token", "refresh_token"])(
      "redacts a %s query param to the literal value 'redacted'",
      (key) => {
        // A route with no "reset"/"verify-email"/"join" segment, so only the
        // query-key rule under test is in play — the path-segment rule has
        // its own tests below.
        const route = redactRoute(`/auth/callback?${key}=super-secret-value`)
        expect(route).toBe(`/auth/callback?${key}=redacted`)
      },
    )

    it.each(["Token", "TOKEN", "Code", "Access_Token"])(
      "matches a sensitive query key case-insensitively (%s)",
      (key) => {
        const route = redactRoute(`/auth/callback?${key}=super-secret-value`)
        expect(route).toBe(`/auth/callback?${key}=redacted`)
      },
    )

    it("redacts only the sensitive keys, leaving the rest of the query intact", () => {
      // `next` is one of the sensitive keys (PR 2 nit, below) precisely
      // because it can itself carry a credential-bearing path — see that
      // fixture for the case that matters. `state` stays untouched here to
      // pin that the redaction is per-key, not "blank the whole query".
      const route = redactRoute("/auth/callback?state=xyz&code=abc123&next=%2Fstudent")
      const params = new URLSearchParams(route.split("?")[1])
      expect(params.get("state")).toBe("xyz")
      expect(params.get("code")).toBe("redacted")
      expect(params.get("next")).toBe("redacted")
    })

    it("redacts a next query param (PR 2 nit, adversarial review)", () => {
      // `?next=` (`lib/nextPath.ts`) is a same-origin *path*, and that path
      // can itself be `/reset/<token>` or `/verify-email/<token>` — a report
      // from `/login?next=/reset/<real-token>` must not write that token to
      // Cloud Logging through the query string.
      const route = redactRoute("/login?next=%2Freset%2Fa1b2c3d4e5f6g7h8i9j0")
      expect(route).toBe("/login?next=redacted")
    })

    it("redacts more than one sensitive key in the same query string", () => {
      const route = redactRoute("/auth/callback?access_token=aaa&refresh_token=bbb")
      const params = new URLSearchParams(route.split("?")[1])
      expect(params.get("access_token")).toBe("redacted")
      expect(params.get("refresh_token")).toBe("redacted")
    })

    it("end to end via buildClientErrorReport: the route field is redacted", () => {
      const report = buildClientErrorReport(
        baseInput({ route: "/join?token=abcdef123456" }),
      )
      expect(report.route).toBe("/join?token=redacted")
    })

    describe("path-segment redaction", () => {
      // Every credential this app puts in a URL at all is a path segment,
      // not a query param — see routes.tsx's /reset/:token,
      // /verify-email/:token and /join/:code, none of which sit inside a
      // portal ErrorBoundary.
      it("redacts the segment after /reset", () => {
        expect(redactRoute("/reset/a1b2c3d4e5f6g7h8i9j0")).toBe("/reset/redacted")
      })

      it("redacts the segment after /verify-email", () => {
        expect(redactRoute("/verify-email/a1b2c3d4e5f6g7h8i9j0")).toBe(
          "/verify-email/redacted",
        )
      })

      it("redacts the segment after /join", () => {
        expect(redactRoute("/join/abc123")).toBe("/join/redacted")
      })

      it("redacts a bare path segment that looks like a UUID even with no route context", () => {
        expect(redactRoute("/teacher/classes/550e8400-e29b-41d4-a716-446655440000")).toBe(
          "/teacher/classes/redacted",
        )
      })

      it("leaves a short path segment alone", () => {
        expect(redactRoute("/teacher/classes/42")).toBe("/teacher/classes/42")
      })

      it("leaves a segment just under the 20-char opaque threshold alone", () => {
        const segment = "a".repeat(19)
        expect(redactRoute(`/teacher/classes/${segment}`)).toBe(`/teacher/classes/${segment}`)
      })

      it("redacts a path segment of exactly 20 chars", () => {
        const segment = "a".repeat(20)
        expect(redactRoute(`/teacher/classes/${segment}`)).toBe("/teacher/classes/redacted")
      })

      it("redacts both a path segment and a query key on the same route", () => {
        const route = redactRoute("/reset/a1b2c3d4e5f6g7h8i9j0?state=xyz")
        expect(route).toBe("/reset/redacted?state=xyz")
      })

      it("redacts a path segment and a next query param together", () => {
        // The realistic shape of the fixture above the describe block:
        // `/reset/:token` redacted by the path rule, `?next=` redacted by
        // the query-key rule, on the same route.
        const route = redactRoute("/reset/a1b2c3d4e5f6g7h8i9j0?next=%2Flogin")
        expect(route).toBe("/reset/redacted?next=redacted")
      })

      it("end to end via buildClientErrorReport: a reset token in the path is redacted", () => {
        const report = buildClientErrorReport(
          baseInput({ route: "/reset/a1b2c3d4e5f6g7h8i9j0" }),
        )
        expect(report.route).toBe("/reset/redacted")
      })
    })

    it("never touches a hash — redactRoute only ever receives pathname+search", () => {
      // Contract: callers pass `pathname + search`, never the hash, so this
      // just pins that redactRoute does not itself try to parse one out —
      // a `#` is ordinary route text as far as this function is concerned.
      expect(redactRoute("/student/board#section")).toBe("/student/board#section")
    })
  })
})

describe("ReportThrottle", () => {
  /** A report shape distinguished only by the fields ReportThrottle keys
   * on — message, stack, route — since `shouldReport` takes exactly that
   * subset of `ClientErrorReport`. */
  function report(
    overrides: Partial<Pick<ClientErrorReport, "message" | "stack" | "route">> = {},
  ): Pick<ClientErrorReport, "message" | "stack" | "route"> {
    return { message: "boom", stack: "at x", route: "/student/board", ...overrides }
  }

  /** A clock this test fully controls, distinct from any wall-clock read —
   * `ReportThrottle`'s constructor takes `() => number` precisely so a test
   * never has to fake global timers to pin rolling-window behaviour. */
  function fakeClock(startAt = 0) {
    let now = startAt
    return { now: () => now, advance: (ms: number) => (now += ms) }
  }

  it("allows the first report", () => {
    const throttle = new ReportThrottle(fakeClock().now)
    expect(throttle.shouldReport(report())).toBe(true)
  })

  it("allows up to 5 distinct reports within a minute, then drops the 6th", () => {
    const clock = fakeClock()
    const throttle = new ReportThrottle(clock.now)
    for (let i = 0; i < 5; i += 1) {
      // Distinct routes so the duplicate rule cannot be what is allowing
      // or blocking any of these — this test is about the count alone.
      expect(throttle.shouldReport(report({ route: `/student/subject/${i}` }))).toBe(true)
      clock.advance(1)
    }
    expect(throttle.shouldReport(report({ route: "/student/subject/5" }))).toBe(false)
  })

  it("frees up a slot once the oldest report ages out of the 60s window", () => {
    const clock = fakeClock()
    const throttle = new ReportThrottle(clock.now)
    for (let i = 0; i < 5; i += 1) {
      throttle.shouldReport(report({ route: `/student/subject/${i}` }))
    }
    expect(throttle.shouldReport(report({ route: "/student/subject/blocked" }))).toBe(false)

    // The first of the five is now exactly 60s old; the sliding window drops
    // it and a 6th distinct report is allowed again.
    clock.advance(60_000)
    expect(throttle.shouldReport(report({ route: "/student/subject/allowed" }))).toBe(true)
  })

  it("keeps the window rolling rather than resetting in fixed buckets", () => {
    const clock = fakeClock()
    const throttle = new ReportThrottle(clock.now)
    throttle.shouldReport(report({ route: "/a" })) // t=0
    clock.advance(50_000)
    for (let i = 0; i < 4; i += 1) {
      throttle.shouldReport(report({ route: `/b${i}` })) // t=50s, 5 in the window now
    }
    // t=50s: 5 reports sent in the last 60s (the one at t=0 has not aged out
    // yet — a fixed-bucket limiter reset at t=0/t=60 would wrongly allow
    // this; a true sliding window must not.
    expect(throttle.shouldReport(report({ route: "/c" }))).toBe(false)

    // Once the t=0 report is more than 60s old (t=61s), one slot frees up.
    clock.advance(11_000)
    expect(throttle.shouldReport(report({ route: "/c" }))).toBe(true)
  })

  it("drops an exact duplicate (same message + stack + route) seen moments ago", () => {
    const throttle = new ReportThrottle(fakeClock().now)
    expect(throttle.shouldReport(report())).toBe(true)
    expect(throttle.shouldReport(report())).toBe(false)
  })

  it("treats a different message, stack, or route as a distinct report", () => {
    const throttle = new ReportThrottle(fakeClock().now)
    expect(throttle.shouldReport(report({ message: "boom" }))).toBe(true)
    expect(throttle.shouldReport(report({ message: "crash" }))).toBe(true)
    expect(throttle.shouldReport(report({ stack: "at y" }))).toBe(true)
    expect(throttle.shouldReport(report({ route: "/teacher/classes" }))).toBe(true)
  })

  it("treats a null stack as its own identity, not interchangeable with a real one", () => {
    const throttle = new ReportThrottle(fakeClock().now)
    expect(throttle.shouldReport(report({ stack: null }))).toBe(true)
    expect(throttle.shouldReport(report({ stack: "at x" }))).toBe(true)
  })

  it("a suppressed duplicate does not itself consume a rate-limit slot", () => {
    // Repeatedly re-reporting the same known failure must not crowd out an
    // unrelated one that shows up moments later — the duplicate check runs
    // before the count is incremented, so it never touches the budget.
    const clock = fakeClock()
    const throttle = new ReportThrottle(clock.now)
    expect(throttle.shouldReport(report())).toBe(true) // consumes slot 1 of 5
    for (let i = 0; i < 10; i += 1) {
      expect(throttle.shouldReport(report())).toBe(false) // duplicate, every time
    }
    // 4 slots remain, exactly as if the duplicates above never happened.
    for (let i = 0; i < 4; i += 1) {
      expect(throttle.shouldReport(report({ route: `/other/${i}` }))).toBe(true)
    }
    expect(throttle.shouldReport(report({ route: "/other/blocked" }))).toBe(false)
  })

  it("reports the same failure again once the 5-minute duplicate window has passed", () => {
    const clock = fakeClock()
    const throttle = new ReportThrottle(clock.now)
    expect(throttle.shouldReport(report())).toBe(true)
    clock.advance(5 * 60_000 - 1)
    expect(throttle.shouldReport(report())).toBe(false)
    clock.advance(1)
    expect(throttle.shouldReport(report())).toBe(true)
  })

  it("uses Date.now by default when no clock is injected", () => {
    // Only pinning that the default parameter is wired up at all — the
    // rolling-window behaviour itself is covered above with a fake clock,
    // which is the only way to pin it deterministically.
    const throttle = new ReportThrottle()
    expect(throttle.shouldReport(report())).toBe(true)
  })
})
