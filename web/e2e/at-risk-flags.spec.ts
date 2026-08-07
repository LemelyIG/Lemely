import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

const BACKEND_URL = "http://127.0.0.1:8000"

/*
 * Phase 3's named acceptance criterion (BUILD/MISSION.md §4, Phase 3):
 * "at-risk flags verified against seeded scenarios." Two layers, both
 * against the same seeded roster (scripts/seed_e2e.py's
 * `expectedAtRiskReasons`): the raw backend contract, and T-06's rendering
 * of it — plus the acknowledge/undo round trip D3.5 mandates (never a
 * dismissal: a flag stays listed and tagged, never disappears).
 */

interface AtRiskApiFlag {
  reason: string
}
interface AtRiskApiEntry {
  studentId: string
  flags: AtRiskApiFlag[]
}
interface AtRiskApiList {
  students: AtRiskApiEntry[]
}

test.describe("at-risk flags reproduce the seeded scenarios", () => {
  test("GET /api/teacher/at-risk matches expectedAtRiskReasons exactly", async ({ playwright }) => {
    const seed = readSeed()
    const request = await playwright.request.newContext({
      extraHTTPHeaders: { Authorization: `Bearer ${seed.teacher.accessToken}` },
    })

    const res = await request.get(`${BACKEND_URL}/api/teacher/at-risk`)
    expect(res.ok(), await res.text()).toBeTruthy()
    const body = (await res.json()) as AtRiskApiList
    const reasonsById = new Map<string, string[]>(
      body.students.map((s) => [s.studentId, s.flags.map((f) => f.reason)]),
    )

    expect(reasonsById.get(seed.students.declining.userId)).toEqual(
      seed.students.declining.expectedAtRiskReasons,
    )
    expect(reasonsById.get(seed.students.inactive.userId)).toEqual(
      seed.students.inactive.expectedAtRiskReasons,
    )
    // control/correctedPaper carry no flags at all -> absent from the
    // response entirely (the route only ever includes flagged students).
    expect(reasonsById.has(seed.students.control.userId)).toBe(false)
    expect(reasonsById.has(seed.students.correctedPaper.userId)).toBe(false)

    // `reason` is pinned as a real server-side query param, never a
    // client-side re-filter of an unfiltered fetch.
    const filtered = await request.get(`${BACKEND_URL}/api/teacher/at-risk?reason=inactive`)
    const filteredBody = (await filtered.json()) as AtRiskApiList
    expect(filteredBody.students.map((s) => s.studentId)).toEqual([
      seed.students.inactive.userId,
    ])

    await request.dispose()
  })

  test("T-06 renders exactly the flagged students with their reasons, and acknowledge/undo never removes a flag", async ({
    page,
  }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    const { teacher, students } = seed
    const { declining, inactive, control } = students

    await injectSession(page, {
      accessToken: teacher.accessToken,
      userId: teacher.userId,
      role: "teacher",
    })
    await page.goto("/teacher/at-risk")
    await expect(page.getByText("Flagged by trajectory")).toBeVisible({ timeout: 15_000 })

    await expect(page.getByRole("link", { name: declining.displayName })).toBeVisible()
    await expect(page.getByRole("link", { name: inactive.displayName })).toBeVisible()
    await expect(page.getByRole("link", { name: control.displayName })).toHaveCount(0)

    const decliningRow = page.locator("tbody tr").filter({ hasText: declining.displayName })
    await expect(
      decliningRow.getByText("Declining over the last 3 papers: 82% -> 68% -> 55% (27pp drop)."),
    ).toBeVisible()
    const inactiveRow = page.locator("tbody tr").filter({ hasText: inactive.displayName })
    await expect(inactiveRow.getByText(/No papers submitted in \d+ days/)).toBeVisible()

    // ── Acknowledge with a note (D3.5's core interaction) ────────────────────
    await decliningRow.getByRole("button", { name: "Acknowledge" }).click()
    await decliningRow.getByLabel(/Note/).fill("Spoke to them, keeping an eye on it.")
    await decliningRow.getByRole("button", { name: "Confirm acknowledge" }).click()

    // Stays listed and tagged — never disappears.
    await expect(decliningRow.getByText(/^Acknowledged/)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole("link", { name: declining.displayName })).toBeVisible()
    await expect(decliningRow.getByText("Spoke to them, keeping an eye on it.")).toBeVisible()

    // Survives a reload (persisted server-side, not component state).
    await page.reload()
    await expect(page.getByText("Flagged by trajectory")).toBeVisible({ timeout: 15_000 })
    const decliningRowAfterReload = page
      .locator("tbody tr")
      .filter({ hasText: declining.displayName })
    await expect(decliningRowAfterReload.getByText(/^Acknowledged/)).toBeVisible()
    await expect(page.getByRole("link", { name: declining.displayName })).toBeVisible()

    // Undo returns it to unacknowledged, still listed (never a mute).
    await decliningRowAfterReload.getByRole("button", { name: "Undo" }).click()
    await expect(
      decliningRowAfterReload.getByRole("button", { name: "Acknowledge" }),
    ).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole("link", { name: declining.displayName })).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })
})
