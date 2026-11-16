import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { parentRoute } from "@/portals/parent"
import { validChildParam } from "@/portals/parent/shellModel"

const SRC = join(fileURLToPath(new URL("../../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("parent portal uses the shared shell", () => {
  it("the layout element is ParentShell, built on PortalShell", () => {
    expect(read("portals/parent/index.tsx")).toContain("element: <ParentShell />")
    const shell = read("portals/parent/shell.tsx")
    expect(shell).toContain("<PortalShell")
    expect(shell).toContain('portal="parent"')
    expect(shell).toContain("lead: <ChildSwitcher />")
    expect(shell).toContain('<ChildSwitcher className="shell-lg:hidden" />')
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
  it("the shell hides its own offline banner on immersive routes", () => {
    expect(read("components/shell/PortalShell.tsx")).toMatch(/\{immersive \? null : \(\s*<OfflineBanner/)
  })
  it("ShellSidebar renders a lead slot under the wordmark", () => {
    const sidebar = read("components/shell/ShellSidebar.tsx")
    expect(sidebar).toMatch(/lead\?: ReactNode/)
    expect(sidebar.indexOf("{lead ?")).toBeLessThan(sidebar.indexOf("<ShellNavList"))
  })
})

describe("an unknown childId never reaches the tabs or links", () => {
  it("keeps the param while the list is loading or when it is a linked child", () => {
    expect(validChildParam("c1", [], true)).toBe("c1")
    expect(validChildParam("c1", ["c1", "c2"], false)).toBe("c1")
  })
  it("drops a param that is not one of the children once the list has loaded", () => {
    expect(validChildParam("ghost", ["c1"], false)).toBeNull()
    expect(validChildParam("ghost", [], false)).toBeNull()
  })
  it("no param stays null", () => {
    expect(validChildParam(null, ["c1"], false)).toBeNull()
  })
  it("the shell feeds the validated param, not the raw one, to tabs, trail and back target", () => {
    const shell = read("portals/parent/shell.tsx")
    expect(shell).toContain("validChildParam(")
    expect(shell).not.toMatch(/childId: paramChild \?\?/)
  })
})
