import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement as h } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { SessionDetailView, type SessionDetailViewProps } from "@/components/tutoring/session-detail-view"
import { StopSharingSheet } from "@/components/tutoring/stop-sharing-sheet"
import type { Booking, Grant, ViewerAction } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * T23 fix lane · what the two screens' components DO with their inputs.
 *
 * The web runner is `environment: "node"` with no jsdom (D3.20), so these tests
 * render the real components to static markup with `react-dom/server`, and
 * where a behaviour lives in a callback (the C-24 gate, whether the thread may
 * post) they read the callback off the props the component hands its child.
 * Three things are replaced, none of them the code under test:
 *
 *   - `Modal` draws its children inline when `open` (the real one is a portal
 *     into `document.body`, which the server renderer cannot do);
 *   - `NotesThread` records the props it was given;
 *   - `useOnlineStatus` says online.
 *
 * What these tests guard, each proved by a mutation in the lane's export:
 *   1. Cancel and Mark as completed are drawn from `allowedActions`, never from
 *      the state a session is in.
 *   2. The thread may post only when the thread AND `post_note` agree.
 *   3. A student's first note waits for C-24 when the settings say it is unread.
 *   4. The stop-sharing sheet draws every line, and the class line only when
 *      `alsoTeachesClasses` has a name.
 */

const captured = vi.hoisted(() => ({ thread: [] as Array<Record<string, unknown>> }))

vi.mock("@/components/ui/modal", () => ({
  Modal: (props: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    props.open
      ? h("div", { role: "dialog" }, h("h2", null, props.title as never), props.children as never, props.footer as never)
      : null,
}))

vi.mock("@/components/ui/notes-thread", () => ({
  NotesThread: (props: Record<string, unknown>) => {
    captured.thread.push(props)
    return null
  },
}))

vi.mock("@/lib/online", () => ({ useOnlineStatus: () => true, isOnline: () => true }))

const WEB = join(import.meta.dirname, "..", "..")
const SPEC = readFileSync(join(WEB, "..", "docs", "tutoring", "SPEC.md"), "utf8")
const S38 = SPEC.slice(SPEC.indexOf("**S-38 · Tutors & your data**"), SPEC.indexOf("### Teacher (T)"))

/** The SPEC's stop-sharing sentences, parsed out of S-38 rather than copied. */
function specSentence(anchor: string): string {
  const at = S38.indexOf(anchor)
  expect(at, `anchor not in SPEC S-38: ${anchor}`).toBeGreaterThan(-1)
  const open = S38.indexOf('"', at + anchor.length)
  return S38.slice(open + 1, S38.indexOf('"', open + 1))
}
const SPEC_LINE_STOPS = specSentence("(confirm sheet:")
const SPEC_LINE_CLASS = specSentence("is non-empty,")
const SPEC_LINE_COUNTED = specSentence("and always")

// ── Fixtures ────────────────────────────────────────────────────────────────

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
    student: { studentId: "s1", displayName: "Maya R." },
    requestedBy: "student",
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
  }
}

function grant(alsoTeachesClasses: string[]): Pick<Grant, "tutor" | "alsoTeachesClasses"> {
  return { tutor: booking().tutor, alsoTeachesClasses }
}

const noop = () => undefined

function viewProps(overrides: Partial<SessionDetailViewProps> = {}): SessionDetailViewProps {
  return {
    booking: booking(),
    viewer: "student",
    notes: {
      items: [],
      canPost: true,
      loading: false,
      error: null,
      retry: noop,
      hasMore: false,
      loadingMore: false,
      moreFailed: false,
      loadMore: noop,
      post: { run: async () => undefined, pending: false, error: null },
    },
    cancel: { run: async () => undefined, pending: false, error: null },
    complete: { run: async () => undefined, pending: false, error: null },
    ...overrides,
  }
}

function render(props: SessionDetailViewProps): string {
  return renderToStaticMarkup(
    h(
      QueryClientProvider,
      { client: new QueryClient() },
      h(MemoryRouter, null, h(SessionDetailView, props)),
    ),
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

beforeEach(() => {
  captured.thread.length = 0
})

/** The props the view gave its notes thread on its last render. */
function threadProps(props: SessionDetailViewProps): Record<string, unknown> {
  render(props)
  const last = captured.thread.at(-1)
  expect(last, "the view never drew a notes thread").toBeDefined()
  return last as Record<string, unknown>
}

// ── 1 · controls come from allowedActions ──────────────────────────────────

describe("SessionDetailView draws Cancel and Mark as completed from allowedActions only", () => {
  it("a confirmed session with no Cancel in allowedActions has no Cancel button", () => {
    const text = words(render(viewProps({ booking: booking({ effectiveState: "accepted", allowedActions: [] }) })))
    expect(text).not.toContain("Cancel session")
    expect(text).not.toContain("You can cancel up to 24 hours")
  })

  it("a confirmed session with Cancel in allowedActions has the button and the rule line", () => {
    const text = words(render(viewProps({ booking: booking({ effectiveState: "accepted", allowedActions: ["cancel"] }) })))
    expect(text).toContain("Cancel session")
    expect(text).toContain("You can cancel up to 24 hours before the start.")
  })

  it("a waiting request with Cancel is a withdrawal, and without it has no button", () => {
    const withIt = words(render(viewProps({ booking: booking({ effectiveState: "requested", allowedActions: ["cancel"] }) })))
    expect(withIt).toContain("Withdraw request")
    const without = words(render(viewProps({ booking: booking({ effectiveState: "requested", allowedActions: [] }) })))
    expect(without).not.toContain("Withdraw request")
    expect(without).not.toContain("Cancel session")
  })

  it("Mark as completed needs the action, whatever the state", () => {
    const needs: ViewerAction[] = ["complete"]
    const ended = words(render(viewProps({ booking: booking({ effectiveState: "awaiting_outcome", allowedActions: needs }) })))
    expect(ended).toContain("Mark as completed")
    for (const state of ["awaiting_outcome", "accepted", "completed"] as const) {
      const text = words(render(viewProps({ booking: booking({ effectiveState: state, allowedActions: [] }) })))
      expect(text, state).not.toContain("Mark as completed")
    }
  })

  it("a tutor-only action in allowedActions draws nothing for a student", () => {
    const text = words(
      render(viewProps({ booking: booking({ effectiveState: "accepted", allowedActions: ["cancel_with_reason", "no_show", "accept"] }) }),
      ),
    )
    expect(text).not.toContain("Cancel session")
    expect(text).not.toContain("Mark as completed")
  })

  it("a parent gets Cancel only on a booking they asked for", () => {
    const mine = words(
      render(viewProps({ viewer: "parent", booking: booking({ requestedBy: "parent", allowedActions: ["cancel"] }) })),
    )
    expect(mine).toContain("Cancel session")
    const childs = words(
      render(viewProps({ viewer: "parent", booking: booking({ requestedBy: "student", allowedActions: ["cancel"] }) })),
    )
    expect(childs).not.toContain("Cancel session")
  })
})

// ── 2 · the thread may post only when both agree ───────────────────────────

describe("SessionDetailView gives the notes thread canPost only when the thread and post_note agree", () => {
  const withNote = booking({ allowedActions: ["post_note"] })

  it.each([
    ["both agree", true, ["post_note"], true],
    ["the thread says yes but post_note is missing", true, [], false],
    ["post_note is there but the thread says no", false, ["post_note"], false],
    ["neither", false, [], false],
  ] as Array<[string, boolean, ViewerAction[], boolean]>)("%s", (_label, threadSays, allowed, expected) => {
    const base = viewProps({ booking: booking({ allowedActions: allowed }) })
    const props = viewProps({ booking: base.booking, notes: { ...base.notes, canPost: threadSays } })
    expect(threadProps(props).canPost).toBe(expected)
  })

  it("a parent's thread never posts, and gets no way to", () => {
    const base = viewProps({ viewer: "parent", booking: withNote })
    const props = viewProps({ viewer: "parent", booking: withNote, notes: { ...base.notes, post: undefined } })
    const thread = threadProps(props)
    expect(thread.canPost).toBe(false)
    expect(thread.onPost).toBeUndefined()
  })
})

// ── 3 · C-24 comes before a student's first note ───────────────────────────

describe("SessionDetailView holds a student's note until the safety notice is read (C-24)", () => {
  function gated(acknowledged: boolean | null) {
    const run = vi.fn(async (_body: string) => "sent")
    const base = viewProps({ booking: booking({ allowedActions: ["post_note"] }) })
    const props = viewProps({
      booking: base.booking,
      notes: { ...base.notes, post: { run, pending: false, error: null } },
      safetyNotice: { acknowledged, acknowledge: { run: async () => undefined, pending: false, error: null } },
    })
    const onPost = threadProps(props).onPost as (body: string) => Promise<unknown>
    return { run, onPost }
  }

  it("unread: the note is not sent, and the draft is kept (the call rejects)", async () => {
    const { run, onPost } = gated(false)
    await expect(onPost("hello")).rejects.toThrow()
    expect(run).not.toHaveBeenCalled()
  })

  it("read: the note is sent", async () => {
    const { run, onPost } = gated(true)
    await expect(onPost("hello")).resolves.toBe("sent")
    expect(run).toHaveBeenCalledWith("hello")
  })

  it("unknown (settings still loading): sent, and the server's 409 raises the notice", async () => {
    const { run, onPost } = gated(null)
    await onPost("hello")
    expect(run).toHaveBeenCalledWith("hello")
  })

  it("a safety_notice_required refusal is passed on so the draft is kept", async () => {
    const refusal = new ApiError(409, "safety_notice_required")
    refusal.detail = { code: "safety_notice_required", message: "x" }
    const base = viewProps({ booking: booking({ allowedActions: ["post_note"] }) })
    const props = viewProps({
      booking: base.booking,
      notes: {
        ...base.notes,
        post: {
          run: async () => {
            throw refusal
          },
          pending: false,
          error: null,
        },
      },
      safetyNotice: { acknowledged: true, acknowledge: { run: async () => undefined, pending: false, error: null } },
    })
    const onPost = threadProps(props).onPost as (body: string) => Promise<unknown>
    await expect(onPost("hello")).rejects.toBe(refusal)
  })
})

// ── 4 · the stop-sharing sheet ─────────────────────────────────────────────

function sheet(classes: string[]): string {
  return renderToStaticMarkup(
    h(StopSharingSheet, { open: true, grant: grant(classes), onConfirm: noop, onCancel: noop }),
  )
}

describe("StopSharingSheet draws every line the SPEC lists, the class line only when there is a class", () => {
  it("with no class: two lines, the SPEC's first and last, and nothing about classes", () => {
    const html = sheet([])
    const text = words(html)
    expect(text).toContain(SPEC_LINE_STOPS)
    expect(text).toContain(SPEC_LINE_COUNTED)
    expect(text).not.toMatch(/also teaches/)
    expect(html.match(/<p class="m-0 text-body-md text-ink">/g)).toHaveLength(2)
  })

  it("with a class: three lines, in the SPEC's order, naming the class", () => {
    const html = sheet(["Maths 10A"])
    const text = words(html)
    const classLine = SPEC_LINE_CLASS.replace("{name}", "Maths 10A")
    const at = [SPEC_LINE_STOPS, classLine, SPEC_LINE_COUNTED].map((line) => text.indexOf(line))
    expect(at.every((i) => i >= 0), `lines found at ${at.join(",")}`).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(html.match(/<p class="m-0 text-body-md text-ink">/g)).toHaveLength(3)
  })

  it("names several classes in the one line, as plain text", () => {
    const html = sheet(["Maths 10A", "<b>Physics</b>"])
    expect(words(html)).toContain("your classes Maths 10A and <b>Physics</b>,")
    expect(html).not.toContain("<b>Physics</b>")
  })

  it("is the tutor's name in the title, with Keep sharing before Stop sharing", () => {
    const text = words(sheet([]))
    expect(text).toContain("Stop sharing with Nour A.?")
    expect(text.indexOf("Keep sharing")).toBeGreaterThan(-1)
    expect(text.indexOf("Keep sharing")).toBeLessThan(text.lastIndexOf("Stop sharing"))
  })

  it("is nothing before a grant is chosen, and nothing while closed", () => {
    expect(renderToStaticMarkup(h(StopSharingSheet, { open: true, grant: null, onConfirm: noop, onCancel: noop }))).toBe("")
    expect(
      renderToStaticMarkup(h(StopSharingSheet, { open: false, grant: grant([]), onConfirm: noop, onCancel: noop })),
    ).toBe("")
  })
})

describe("these tests read the SPEC, not themselves", () => {
  it("found the three SPEC sentences", () => {
    expect(SPEC_LINE_STOPS).toMatch(/^They can't see your progress/)
    expect(SPEC_LINE_CLASS).toContain("{name}")
    expect(SPEC_LINE_COUNTED).toMatch(/^Your grades are still counted/)
  })
})

// ── 5 · where focus goes (read from the source: effects do not run on the server) ──

function effectBlocks(code: string): string[] {
  const starts = [...code.matchAll(/useEffect\(/g)].map((m) => m.index ?? 0)
  return starts.map((at, i) => code.slice(at, starts[i + 1] ?? code.length))
}

function code(file: string): string {
  return stripComments(readFileSync(join(WEB, file), "utf8"))
}

describe("focus order", () => {
  const view = code("src/components/tutoring/session-detail-view.tsx")

  it("the heading is focused only by an effect that waits for the confirm sheet to be gone", () => {
    const focusing = effectBlocks(view).filter((block) => block.includes("headingRef.current?.focus()"))
    expect(focusing).toHaveLength(1)
    const [effect] = focusing
    expect(effect).toContain("openConfirm")
    expect(effect).toContain("setConfirm(null)")
    // The state-change effect only marks the heading as owed.
    const marking = effectBlocks(view).filter((block) => block.includes("lastState.current"))
    expect(marking).toHaveLength(1)
    expect(marking[0]).not.toContain(".focus(")
    expect(marking[0]).toContain("setHeadingOwed(true)")
  })

  it("no sheet is mounted without a chosen action", () => {
    expect(view).toContain('confirm === "complete" ? complete : undefined')
  })

  const access = code("src/portals/student/screens/tutoring/TutorAccess.tsx")

  it("leaving a class unmounts the sheet and sends focus to the next section when none are left", () => {
    const at = access.indexOf("function ClassesSection")
    const section = access.slice(at, access.indexOf("function CountingSection", at))
    expect(at).toBeGreaterThan(-1)
    expect(section.length).toBeGreaterThan(200)
    expect(section).toContain("useFocusWhenRowGone(")
    expect(section).toContain('"tutor-access-counting"')
    expect(section).toContain("markLeft(target.classId)")
    expect(section).toContain("setTarget(null)")
    expect(access).toContain("function focusHeading(id: string)")
    expect(access).toMatch(/<h2 id=\{id\} tabIndex=\{-1\}/)
  })

  /* T33 (S-38): Stop sharing removed the row whose button had opened the sheet, so focus fell to
     the body. It now goes to the Sharing heading once the list has dropped the grant. */
  it("stopping a grant unmounts the sheet and sends focus to the Sharing heading", () => {
    const at = access.indexOf("function SharingSection")
    const section = access.slice(at, access.indexOf("// ── 2 · Who looked", at))
    expect(at).toBeGreaterThan(-1)
    expect(section.length).toBeGreaterThan(200)
    expect(section).toContain("useFocusWhenRowGone(")
    expect(section).toContain("splitGrants(grants.data.items).live")
    expect(section).toContain('"tutor-access-sharing"')
    // Marked only after the call succeeded, and the sheet is unmounted in the same step.
    const stop = section.slice(section.indexOf("async function stop()"), section.indexOf("return ("))
    expect(stop.indexOf("await revoke.mutateAsync")).toBeGreaterThan(-1)
    expect(stop.indexOf("markStopped(target.grantId)")).toBeGreaterThan(stop.indexOf("await revoke.mutateAsync"))
    expect(stop).toContain("setTarget(null)")
    // The id it names is a real heading that can take programmatic focus.
    expect(access).toMatch(/<Section id="tutor-access-sharing" title="Sharing">/)
  })
})
