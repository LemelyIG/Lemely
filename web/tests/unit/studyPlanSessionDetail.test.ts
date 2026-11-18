import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { SessionVM } from "@/portals/student/screens/studyplan/planModel"
import { SessionDetail, SessionPanel, SessionSheet, type SessionActions } from "@/portals/student/screens/studyplan/SessionDetail"

const session: SessionVM = {
  id: "s1", subjectCode: "0580", subjectName: "Mathematics", dotIndex: 0,
  activity: "practice", activityLabel: "Practice set", title: "Vectors", minutes: 15,
  minutesLabel: "15 min", date: "2026-08-06", dayShort: "Thu", anyDay: false,
  status: "today", why: null, whyBody: "Work on vectors.", start: null,
  canMove: true, moveDays: [{ date: "2026-08-07", label: "Fri" }],
}
const actions: SessionActions = { completing: false, completeError: null, movingTo: null, onStart: () => {}, onComplete: () => {}, onMove: () => {} }
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
    const html = detail({ start: { label: "Start · +9 marks", path: "/student/practice" } })
    expect(html).toContain("Start · +9 marks")
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
  it("opens an adaptive sheet with no close button, since the overlay, Escape and the grabber dismiss it", () => {
    const el = sheet(session)
    expect(el.props.open).toBe(true)
    expect(el.props.children?.props.side).toBe("adaptive")
    expect(el.props.children?.props.showCloseButton).toBe(false)
  })
})
