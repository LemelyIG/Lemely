import { describe, expect, it } from "vitest"
import {
  DEFAULT_PUSH_URL,
  GENERIC_PUSH_BODY,
  GENERIC_PUSH_TITLE,
  decidePushNotification,
  pickClientToFocus,
  sameOriginPath,
} from "@/lib/push/pushDecision"

/*
 * The push decision logic (P5.9 chunk A, D5.15 §4).
 *
 * This is the only testable half of the push path, and that is a measured
 * constraint rather than a preference: this machine has no VAPID keys, so the
 * transport reports itself unavailable by design (D5.9 §4) and **no real push
 * can be delivered in any harness in this build**. vitest also runs
 * `environment: "node"` with no jsdom and no `ServiceWorkerGlobalScope`. So the
 * honest claim these tests support is "the decision is right", never "a push
 * was delivered".
 *
 * Two properties carry the file. First, something is *always* returned —
 * browsers require some notification per push, so a handler that decides on
 * nothing is a bug the reader sees as the engine's own "This site has been
 * updated in the background". Second, a reply is untrusted: it arrives over a
 * message channel, and the click target it carries decides where a reader who
 * believes they are still inside the app actually lands.
 */

describe("decidePushNotification", () => {
  it("falls back to the generic notification when no page answered", () => {
    // The normal state with the app closed — the standing cost of D5.10's
    // payload-less push, not an error path.
    expect(decidePushNotification(null)).toEqual({
      title: GENERIC_PUSH_TITLE,
      body: GENERIC_PUSH_BODY,
      url: DEFAULT_PUSH_URL,
    })
  })

  it.each([
    ["undefined", undefined],
    ["a string", "grades ready"],
    ["a number", 7],
    ["an array", []],
    ["an empty object", {}],
    ["a titleless reply", { body: "3 marks were adjusted" }],
    ["a blank title", { title: "   ", body: "b" }],
    ["a non-string title", { title: 42, body: "b" }],
  ])("falls back when the reply is %s", (_label, reply) => {
    expect(decidePushNotification(reply).title).toBe(GENERIC_PUSH_TITLE)
  })

  it("uses a real title and body when a page supplied them", () => {
    expect(
      decidePushNotification({
        title: "Your paper has been marked",
        body: "0625/42 — 63/80",
        url: "/notifications",
      }),
    ).toEqual({
      title: "Your paper has been marked",
      body: "0625/42 — 63/80",
      url: "/notifications",
    })
  })

  it("keeps a real title when the notification genuinely has no body", () => {
    // `NotificationDTO.body` is nullable on the backend, so this is a real
    // notification shape and not a malformed reply. Discarding it down to a
    // fully generic notification would throw away the one true thing we know.
    const decided = decidePushNotification({ title: "New announcement", body: null })
    expect(decided.title).toBe("New announcement")
    expect(decided.body).toBe(GENERIC_PUSH_BODY)
  })

  it("trims surrounding whitespace rather than rendering it", () => {
    const decided = decidePushNotification({ title: "  Streak at risk  ", body: " tonight " })
    expect(decided.title).toBe("Streak at risk")
    expect(decided.body).toBe("tonight")
  })

  it("returns a renderable notification for every shape a cloned reply can take", () => {
    // A reply crosses a message channel, so it is structured-cloned: it can only
    // ever be plain data, and an exotic object with a throwing getter cannot
    // survive the clone to reach this function. What *can* arrive is any plain
    // shape at all, so the property worth pinning is totality over those — every
    // input yields a title and body a browser can render.
    const replies: unknown[] = [
      null,
      undefined,
      0,
      "",
      [],
      {},
      { title: null },
      { title: "", body: "" },
      { title: "ok", body: 5, url: {} },
      { title: "ok", extra: { deeply: { nested: true } } },
    ]
    for (const reply of replies) {
      const decided = decidePushNotification(reply)
      expect(typeof decided.title).toBe("string")
      expect(decided.title.length).toBeGreaterThan(0)
      expect(typeof decided.body).toBe("string")
      expect(decided.body.length).toBeGreaterThan(0)
      expect(decided.url.startsWith("/")).toBe(true)
    }
  })
})

describe("sameOriginPath", () => {
  it("accepts a rooted relative path", () => {
    expect(sameOriginPath("/notifications")).toBe("/notifications")
  })

  it.each([
    ["a protocol-relative URL", "//evil.example/steal"],
    ["a backslash-rooted URL", "/\\evil.example"],
    ["an absolute http URL", "http://evil.example"],
    ["a javascript: URL", "javascript:alert(1)"],
    ["a bare relative path", "notifications"],
    ["an empty string", ""],
    ["whitespace", "   "],
    ["a non-string", 7],
  ])("rejects %s", (_label, value) => {
    expect(sameOriginPath(value)).toBeNull()
  })

  it("sends a rejected target to the default rather than dropping the notification", () => {
    // The notification still shows; only the untrusted destination is discarded.
    const decided = decidePushNotification({
      title: "Your paper has been marked",
      url: "//evil.example/steal",
    })
    expect(decided.title).toBe("Your paper has been marked")
    expect(decided.url).toBe(DEFAULT_PUSH_URL)
  })
})

describe("pickClientToFocus", () => {
  it("returns null when nothing is open", () => {
    expect(pickClientToFocus([])).toBeNull()
  })

  it("prefers the focused page over a merely visible one", () => {
    const visible = { visibilityState: "visible" }
    const focused = { focused: true, visibilityState: "visible" }
    expect(pickClientToFocus([visible, focused])).toBe(focused)
  })

  it("prefers a visible page over a hidden one", () => {
    const hidden = { visibilityState: "hidden" }
    const visible = { visibilityState: "visible" }
    expect(pickClientToFocus([hidden, visible])).toBe(visible)
  })

  it("falls back to the first page when none is focused or visible", () => {
    const first = { visibilityState: "hidden" }
    expect(pickClientToFocus([first, { visibilityState: "hidden" }])).toBe(first)
  })
})
