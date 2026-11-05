import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { teacherRoute } from "@/portals/teacher"
import {
  TEACHER_SETTINGS_TABS,
  activeSettingsTab,
  settingsTabPath,
} from "@/portals/settings/settingsTabs"
import { signOutOrder } from "@/portals/settings/signOutEverywhere"

/*
 * The teacher Settings dialog: one tab per route, in step with the route
 * block in `portals/teacher/index.tsx`, and still reachable at every path the
 * page-based settings used.
 */

const BASE = "/teacher/settings"

function settingsRoute() {
  const route = (teacherRoute.children ?? []).find((child) => child.path === "settings")
  if (!route) throw new Error("teacher portal has no settings route")
  return route
}

describe("TEACHER_SETTINGS_TABS", () => {
  it("lists the tabs in rail order", () => {
    expect(TEACHER_SETTINGS_TABS.map((tab) => tab.label)).toEqual([
      "Profile",
      "Account and devices",
      "Notifications",
      "Appearance",
      "Classes and grading",
      "Install Lemely",
    ])
  })

  it("gives every tab a unique id, segment and a helper sentence", () => {
    const ids = TEACHER_SETTINGS_TABS.map((tab) => tab.id)
    const segments = TEACHER_SETTINGS_TABS.map((tab) => tab.segment)
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(segments).size).toBe(segments.length)
    for (const tab of TEACHER_SETTINGS_TABS) {
      expect(tab.description.trim().length, tab.id).toBeGreaterThan(0)
      // No em dashes in UI copy.
      expect(tab.description).not.toContain("—")
      expect(tab.label).not.toContain("—")
    }
  })

  it("keeps the paths the page-based settings used", () => {
    const paths = TEACHER_SETTINGS_TABS.map((tab) => settingsTabPath(BASE, tab))
    for (const legacy of [BASE, `${BASE}/devices`, `${BASE}/notifications`, `${BASE}/install`]) {
      expect(paths).toContain(legacy)
    }
  })

  it("includes every screen the top-level /settings lane offers", () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), "src/portals/settings/SettingsFrame.tsx"),
      "utf8",
    )
    const block = source.slice(source.indexOf("const SETTINGS_NAV = ["))
    const topLevel = [...block.slice(0, block.indexOf("]")).matchAll(/label:\s*"([^"]+)"/g)].map(
      (m) => m[1],
    )
    expect(topLevel.length).toBeGreaterThan(0)
    const labels = TEACHER_SETTINGS_TABS.map((tab) => tab.label)
    for (const label of topLevel) expect(labels).toContain(label)
  })
})

describe("route mapping", () => {
  it("mounts exactly one child route per tab, index for the empty segment", () => {
    const children = settingsRoute().children ?? []
    const mounted = children.map((child) => (child.index ? "" : child.path))
    expect(mounted.sort()).toEqual(TEACHER_SETTINGS_TABS.map((tab) => tab.segment).sort())
  })

  it("titles every tab route", () => {
    for (const child of settingsRoute().children ?? []) {
      expect((child.handle as { title?: string } | undefined)?.title, String(child.path)).toBeTruthy()
    }
  })

  it("resolves the active tab from a pathname", () => {
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, BASE)?.id).toBe("profile")
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, `${BASE}/`)?.id).toBe("profile")
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, `${BASE}/devices`)?.id).toBe("account")
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, `${BASE}/appearance`)?.id).toBe(
      "appearance",
    )
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, `${BASE}/classes/`)?.id).toBe("classes")
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, `${BASE}/nope`)).toBeNull()
    expect(activeSettingsTab(TEACHER_SETTINGS_TABS, BASE, "/teacher/classes")).toBeNull()
  })

  it("builds tab paths from the base", () => {
    expect(settingsTabPath(BASE, { segment: "" })).toBe(BASE)
    expect(settingsTabPath(BASE, { segment: "notifications" })).toBe(`${BASE}/notifications`)
  })
})

describe("signOutOrder", () => {
  it("revokes this device last, so the token survives until the others are gone", () => {
    expect(
      signOutOrder([
        { deviceId: "here", isCurrent: true },
        { deviceId: "phone", isCurrent: false },
        { deviceId: "laptop", isCurrent: false },
      ]),
    ).toEqual(["phone", "laptop", "here"])
  })

  it("handles a list with no current device, and an empty list", () => {
    expect(signOutOrder([{ deviceId: "a", isCurrent: false }])).toEqual(["a"])
    expect(signOutOrder([])).toEqual([])
  })
})
