import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { parentRoute } from "@/portals/parent"
import { parentTabs, resolveChildId, validChildParam } from "@/portals/parent/shellModel"

const SRC = join(fileURLToPath(new URL("../../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("parent portal uses the shared shell", () => {
  it("the layout element is ParentShell, built on PortalShell", () => {
    expect(read("portals/parent/index.tsx")).toContain("element: <ParentShell />")
    const shell = read("portals/parent/shell.tsx")
    expect(shell).toContain("<PortalShell")
    expect(shell).toContain('portal="parent"')
    // The rail pill spans the rail (mock rail2 .kid is full width).
    expect(shell).toContain('lead: <ChildSwitcher className="w-full" />')
    expect(shell).toContain('<ChildSwitcher className="shell-lg:hidden" />')
  })
  it("the switcher pill gives its name up below 414px so the page title keeps its room", () => {
    const pill = read("portals/parent/ChildSwitcher.tsx")
    expect(pill).toContain("truncate max-phone:hidden")
    // The select still names the control and carries the current child for assistive tech.
    expect(pill).toContain('aria-label="Choose which child to view"')
  })
  it("the old bespoke header is gone", () => {
    const index = read("portals/parent/index.tsx")
    for (const gone of ["function Header", "function ParentTrail", "function ChildSwitcher", "function ParentLayout"]) expect(index).not.toContain(gone)
  })
  it("mounts a Topics route that still shows Weaknesses, and keeps the old path", () => {
    const paths = (parentRoute.children ?? []).map((r) => r.path)
    expect(paths).toContain("children/:childId/topics")
    expect(paths).toContain("children/:childId/weaknesses")
    expect(paths.at(-1)).toBe("*")
  })
  it("the account menu links the Emails settings screen", () => {
    expect(read("portals/parent/shell.tsx")).toMatch(/\{ id: "emails", label: "Emails", to: "\/parent\/emails"/)
  })
  it("the shell hides its offline banner only on a route with its own (ownOfflineBanner), never on immersive alone", () => {
    const shell = read("components/shell/PortalShell.tsx")
    expect(shell).toMatch(/\{ownOfflineBanner \? null : \(\s*<OfflineBanner/)
    expect(shell).not.toMatch(/\{immersive \? null : \(\s*<OfflineBanner/)
    expect(shell).toMatch(/ownOfflineBanner\?: boolean/)
    expect(read("lib/meta/documentMeta.ts")).toContain("ownOfflineBanner?: true")
  })
  it("ShellSidebar renders a lead slot under the wordmark", () => {
    const sidebar = read("components/shell/ShellSidebar.tsx")
    expect(sidebar).toMatch(/lead\?: ReactNode/)
    expect(sidebar.indexOf("{rail && lead ?")).toBeLessThan(sidebar.indexOf("<ShellNavList"))
  })
})

describe("an unknown childId never reaches the tabs or links", () => {
  it("keeps the param only when it is a linked child", () => {
    expect(validChildParam("c1", ["c1", "c2"])).toBe("c1")
  })
  it("drops a param that is not one of the children", () => {
    expect(validChildParam("ghost", ["c1"])).toBeNull()
  })
  it("drops the param while the list is pending or failed (no children yet)", () => {
    expect(validChildParam("c1", [])).toBeNull()
  })
  it("no param stays null", () => {
    expect(validChildParam(null, ["c1"])).toBeNull()
  })
  it("pending: the tabs are Overview (children list) and Inbox, not the raw URL child", () => {
    expect(parentTabs(resolveChildId(validChildParam("c1", []), [], null)).map((t) => t.to)).toEqual(["/parent", "/parent/notifications"])
  })
  it("the shell feeds the validated param, not the raw one, to tabs, trail and back target", () => {
    const shell = read("portals/parent/shell.tsx")
    expect(shell).toContain("validChildParam(")
    expect(shell).not.toMatch(/childId: paramChild \?\?/)
  })
  it("rail rows use one 18px glyph size, the drawer shows no second switcher", () => {
    const shell = read("portals/parent/shell.tsx")
    expect(shell).not.toContain("icon: item.icon")
    expect(shell).toMatch(/<Glyph size=\{18\} aria-hidden="true" \/>, activeIcon: undefined/)
  })
})
