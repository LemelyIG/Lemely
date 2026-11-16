import { describe, expect, it } from "vitest"
import { parentPageTitle, parentShellTrail, parentTabs, resolveChildId, switchChildPath, topicsActive } from "@/portals/parent/shellModel"

describe("parentTabs (mock pa.js ptab)", () => {
  it("four tabs for a child: Overview, Topics, Inbox, Tutoring", () => {
    expect(parentTabs("c1")).toEqual([
      { id: "overview", label: "Overview", to: "/parent/children/c1", end: true },
      { id: "topics", label: "Topics", to: "/parent/children/c1/topics", end: false },
      { id: "inbox", label: "Inbox", to: "/parent/notifications", end: false },
      { id: "tutoring", label: "Tutoring", to: "/parent/children/c1/tutoring", end: false },
    ])
  })
  it("without a child there is one Overview tab to the children list, exactly, and the Inbox; no duplicate targets", () => {
    const tabs = parentTabs(null)
    expect(tabs.map((t) => t.id)).toEqual(["overview", "inbox"])
    expect(tabs[0]).toMatchObject({ to: "/parent", end: true })
    // At most one tab can match /parent, so at most one is highlighted and carries aria-current.
    const targets = tabs.map((t) => t.to)
    expect(new Set(targets).size).toBe(targets.length)
  })
  it("encodes the id", () => {
    expect(parentTabs("a/b")[0].to).toBe("/parent/children/a%2Fb")
  })
})

describe("resolveChildId", () => {
  it("URL first, then the last child viewed, then the first child", () => {
    expect(resolveChildId("c2", ["c1", "c2"], "c1")).toBe("c2")
    expect(resolveChildId(null, ["c1", "c2"], "c2")).toBe("c2")
    expect(resolveChildId(null, ["c1", "c2"], "gone")).toBe("c1")
    expect(resolveChildId(null, [], null)).toBeNull()
  })
})

describe("parentShellTrail (ported from ParentTrail, index.tsx:178-225)", () => {
  const one = { childId: "c1", hasChildList: false, subjectLabel: null }
  const many = { ...one, hasChildList: true }
  it("overview: one crumb, so no trail row, unless there is a children list", () => {
    expect(parentShellTrail("/parent/children/c1", one)).toEqual([{ label: "Overview" }])
    expect(parentShellTrail("/parent/children/c1/", many)).toEqual([{ label: "Your children", to: "/parent" }, { label: "Overview" }])
  })
  it("topics and the old weaknesses path", () => {
    const want = [{ label: "Overview", to: "/parent/children/c1" }, { label: "Topics" }]
    expect(parentShellTrail("/parent/children/c1/topics", one)).toEqual(want)
    expect(parentShellTrail("/parent/children/c1/weaknesses", one)).toEqual(want)
  })
  it("tutoring, tutor access and a session", () => {
    expect(parentShellTrail("/parent/children/c1/tutor-access", one).map((c) => c.label)).toEqual(["Overview", "Tutoring", "Who they share with"])
    expect(parentShellTrail("/parent/children/c1/sessions/b9", one).map((c) => c.label)).toEqual(["Overview", "Tutoring", "Session"])
  })
  it("a subject uses its cached name, else the code, else This subject", () => {
    expect(parentShellTrail("/parent/children/c1/subjects/0625", { ...one, subjectLabel: "Physics" }).at(-1)).toEqual({ label: "Physics" })
    expect(parentShellTrail("/parent/children/c1/subjects/0625", one).at(-1)).toEqual({ label: "0625" })
  })
  it("no child route, no trail", () => {
    expect(parentShellTrail("/parent/notifications", { ...many, childId: null })).toEqual([])
  })
})

describe("parentPageTitle", () => {
  it.each([
    ["/parent", "Your children"],
    ["/parent/children/c1", "Overview"],
    ["/parent/children/c1/topics", "Topics to work on"],
    ["/parent/children/c1/weaknesses", "Topics to work on"],
    ["/parent/children/c1/tutoring", "Tutoring"],
    ["/parent/children/c1/tutor-access", "Who they share with"],
    ["/parent/children/c1/sessions/b9", "Session details"],
    ["/parent/notifications", "Notifications"],
    ["/parent/tutors", "Tutors"],
    ["/parent/tutors/t1", "Tutor profile"],
    ["/parent/tutors/t1/book", "Book a session"],
    ["/parent/nope", "Page not found"],
  ])("%s → %s", (path, title) => {
    expect(parentPageTitle(path, null)).toBe(title)
  })
  it("a subject page is titled by the subject", () => {
    expect(parentPageTitle("/parent/children/c1/subjects/0625", "Physics")).toBe("Physics")
    expect(parentPageTitle("/parent/children/c1/subjects/0625", null)).toBe("0625")
  })
})

describe("switchChildPath (index.tsx:120-124, plus topics)", () => {
  it("keeps the topics, weaknesses, tutoring and tutor-access tails", () => {
    expect(switchChildPath("/parent/children/c1/topics", "c2")).toBe("/parent/children/c2/topics")
    expect(switchChildPath("/parent/children/c1/weaknesses", "c2")).toBe("/parent/children/c2/weaknesses")
    expect(switchChildPath("/parent/children/c1/tutor-access", "c2")).toBe("/parent/children/c2/tutor-access")
  })
  it("anything else lands on the overview", () => {
    expect(switchChildPath("/parent/children/c1/subjects/0625", "c2")).toBe("/parent/children/c2")
  })
})

describe("topicsActive", () => {
  it("lights the Topics tab on both paths", () => {
    expect([topicsActive("/parent/children/c1/topics"), topicsActive("/parent/children/c1/weaknesses"), topicsActive("/parent/children/c1")]).toEqual([true, true, false])
  })
})
