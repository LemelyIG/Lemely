import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Sheet } from "@/components/ui/sheet"
import type { SessionVM } from "@/portals/student/screens/studyplan/planModel"
import { COPY } from "@/portals/student/screens/studyplan/planCopy"
import { MoveChoices, SessionCloseButton, SessionDetail, SessionPanel, SessionSheet, type SessionActions } from "@/portals/student/screens/studyplan/SessionDetail"

const session: SessionVM = {
  id: "s1", subjectCode: "0580", subjectName: "Mathematics", dotIndex: 0,
  activity: "practice", activityLabel: "Practice set", title: "Vectors", minutes: 15,
  minutesLabel: "15 min", date: "2026-08-06", dayShort: "Thu", anyDay: false,
  status: "today", why: null, whyBody: "Work on vectors.", start: null,
  canMove: true, moveDays: [{ date: "2026-08-07", label: "Fri" }],
}
const actions: SessionActions = { completing: false, completeError: null, movingTo: null, moveBusy: false, onStart: () => {}, onComplete: () => {}, onMove: () => {} }
const detail = (over: Partial<SessionVM> = {}, extra: Partial<SessionActions> = {}) =>
  renderToStaticMarkup(createElement(SessionDetail, { session: { ...session, ...over }, ...actions, ...extra }))
const panel = (s: SessionVM | null, binnyLine: string | null) =>
  renderToStaticMarkup(createElement(SessionPanel, { session: s, binnyLine, ...actions }))

describe("session detail", () => {
  it("shows the session, reason and available actions", () => {
    const html = detail()
    expect(html).toContain("Vectors")
    expect(html).toContain("Work on vectors.")
    expect(html).toContain("Mark done")
    expect(html).toContain('aria-expanded="false"')
  })
  it("shows completion and omits unavailable actions for a completed session", () => {
    const html = detail({ status: "done", canMove: false, start: { label: "Start", path: "/x" } })
    expect(html).toContain("Done")
    expect(html).not.toContain("Mark done")
    expect(html).not.toContain("aria-expanded")
    expect(html).not.toContain("Start")
  })
  it("offers the start action with the model's own label when the session can be started", () => {
    const html = detail({ start: { label: "Start · 9 marks lost", path: "/student/practice" } })
    expect(html).toContain("Start · 9 marks lost")
  })
  it("omits the start action when there is nothing to start", () => {
    expect(detail({ start: null })).not.toContain("Start")
  })
  it("announces a completion error with a retry action", () => {
    const html = detail({}, { completeError: "Could not save" })
    expect(html).toContain('role="alert"')
    expect(html).toContain("Could not save")
    expect(html).toContain("Try again")
    expect(html).not.toContain("Work on vectors.")
  })
  it("disables completion and says so while it saves", () => {
    const html = detail({}, { completing: true })
    expect(html).toContain("Saving…")
    expect(html).toMatch(/<button[^>]*disabled[^>]*>(?:(?!<\/button>).)*Saving…/)
  })
  it("keeps the move choice closed until asked", () => {
    expect(detail()).not.toContain('aria-label="Move to"')
  })
})

describe("the move choice", () => {
  const choices = (over: { busy: boolean; movingTo: string | null }) =>
    renderToStaticMarkup(
      createElement(MoveChoices, {
        session: { ...session, moveDays: [{ date: "2026-08-07", label: "Fri" }, { date: "2026-08-08", label: "Sat" }] },
        onMove: () => {},
        ...over,
      }),
    )
  const disabledCount = (html: string) => (html.match(/<button[^>]*\sdisabled/g) ?? []).length

  it("offers every day, enabled, when nothing is moving", () => {
    const html = choices({ busy: false, movingTo: null })
    expect(html).toContain("Fri")
    expect(html).toContain("Sat")
    expect(disabledCount(html)).toBe(0)
  })
  it("waits while another session's move is in flight, which this session cannot see itself", () => {
    expect(disabledCount(choices({ busy: true, movingTo: null }))).toBe(2)
  })
  it("marks the day this session is moving to", () => {
    const html = choices({ busy: true, movingTo: "2026-08-08" })
    expect(html).toMatch(/aria-pressed="true"[^>]*>Sat|>Sat<\/button>/)
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  })
})

describe("session panel (desktop)", () => {
  it("shows an empty panel without inventing a session", () => {
    const html = panel(null, null)
    expect(html).toContain('aria-label="Session"')
    expect(html).not.toContain("Vectors")
  })
  it("shows the selected session with Binny's line beneath it", () => {
    const html = panel(session, "Nice one")
    expect(html).toContain("Vectors")
    expect(html).toContain("Nice one")
  })
  it("lets Binny speak on its own when nothing is selected", () => {
    const html = panel(null, "Pick one")
    expect(html).toContain("Pick one")
    expect(html).not.toContain("Vectors")
  })
})

describe("session sheet (below 1280px)", () => {
  const sheet = (s: SessionVM | null) => SessionSheet({ session: s, onClose: () => {}, ...actions }) as ReactElement<{ open: boolean; children: ReactElement<Record<string, unknown>> | null }>
  it("is closed and empty without a session", () => {
    const el = sheet(null)
    expect(el.props.open).toBe(false)
    expect(el.props.children).toBeNull()
  })
  it("opens an adaptive sheet without the primitive's own close button, which a phone does not want next to its grabber", () => {
    const el = sheet(session)
    expect(el.props.open).toBe(true)
    expect(el.props.children?.props.side).toBe("adaptive")
    expect(el.props.children?.props.showCloseButton).toBe(false)
  })
  const findDetailEl = (node: unknown): ReactElement<{ closeButton?: ReactElement }> | null => {
    if (Array.isArray(node)) return node.map(findDetailEl).find((hit) => hit !== null) ?? null
    if (typeof node !== "object" || node === null || !("props" in node)) return null
    const el = node as ReactElement<{ children?: unknown; closeButton?: ReactElement }>
    return el.type === SessionDetail ? el : findDetailEl(el.props.children)
  }
  it("hands the session body its own close button, so the floating sheet from sm up can be dismissed by sight (#12)", () => {
    const closeEl = findDetailEl(sheet(session))?.props.closeButton
    expect(closeEl).toBeDefined()
    expect(closeEl?.type).toBe(SessionCloseButton)
  })
  it("draws that button at a 44px target, named for assistive tech, and only from sm up", () => {
    const html = renderToStaticMarkup(createElement(Sheet, { open: true }, createElement(SessionCloseButton)))
    expect(html).toMatch(/<button[^>]*type="button"/)
    expect(html).toMatch(/\bsize-11\b/)
    // A phone keeps its grabber; the button would only crowd it.
    expect(html).toMatch(/\bmax-sm:hidden\b/)
    expect(html).toContain(`>${COPY.closeSession}<`)
    expect(html).toContain('aria-hidden="true"')
    // Logical properties only: it sits at the end edge in a right-to-left page too.
    expect(html).not.toMatch(/\b(?:ml|mr|pl|pr|left|right)-/)
  })
  it("puts the close button in the session body's top row, and leaves the desktop panel without one", () => {
    const withClose = renderToStaticMarkup(
      createElement(SessionDetail, { session, ...actions, closeButton: createElement("i", { id: "stand-in-close" }) }),
    )
    expect(withClose).toContain('id="stand-in-close"')
    expect(detail()).not.toContain("stand-in-close")
    expect(panel(session, null)).not.toContain(COPY.closeSession)
  })
  it("lets the session heading keep its own weight, not the sheet title's font-semibold default", () => {
    // Walk the real sheet tree to the SessionDetail it mounts, then render the title wrapper it hands down.
    const findDetail = (node: unknown): ReactElement<{ titleWrap: (heading: ReactElement) => ReactElement }> | null => {
      if (Array.isArray(node)) return node.map(findDetail).find((hit) => hit !== null) ?? null
      if (typeof node !== "object" || node === null || !("props" in node)) return null
      const el = node as ReactElement<{ children?: unknown; titleWrap: (heading: ReactElement) => ReactElement }>
      return el.type === SessionDetail ? el : findDetail(el.props.children)
    }
    const detailEl = findDetail(sheet(session))
    expect(detailEl).not.toBeNull()
    const heading = createElement("h2", { className: "m-0 font-extrabold" }, "Vectors")
    const title = renderToStaticMarkup(createElement(Sheet, { open: true }, detailEl?.props.titleWrap(heading)))
    expect(title).toContain("<h2")
    expect(title).toContain("font-extrabold")
    expect(title).not.toContain("font-semibold")
  })
})
