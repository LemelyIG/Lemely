import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

// Wire shapes: plan 03 team DTOs, plan 05 summary, the existing classes list.
const seat = {
  kind: "student_seat", memberId: "m1", studentId: "s1", studentName: "Omar Hassan", status: "active", leavesAt: null,
  scopeSubjects: ["0580"], scopeActions: ["mark_paper"], capUnits: null, capPeriod: "month", capUsedUnits: 0, meterFraction: 0.4,
  joinedAt: "2026-10-12T09:00:00Z",
}
const tier = {
  planTierId: "t", code: "teacher_pro_m", name: "Teacher Pro", priceMinor: 90000, currency: "EGP", interval: "monthly",
  audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000, features: {},
}
const summary = {
  beneficiary: { userId: "u", displayName: "T", audience: "teacher" },
  subscription: {
    subscriptionId: "sub-t", status: "active", tier, currentPeriodStart: null, currentPeriodEnd: "2026-12-01T00:00:00Z",
    cancelAtPeriodEnd: false, pendingTier: null, graceUntil: null, extraSeats: 2, pendingExtraSeats: null,
  },
  canManage: true, managedByName: null, savedCard: null,
  usage: { fraction: null, resetsAt: null }, credits: { totalUnits: 0, expiring: [] }, debtUnits: 0, seats: { capacity: 22, used: 1 },
}

test("a teacher turns on weekly study plans for a seat", async ({ page }) => {
  const teacher = readSeed().teacher
  let scopeBody: unknown = null
  await page.route("**/api/teacher/team/seats", (r) => r.fulfill({ json: { seats: [seat] } }))
  await page.route("**/api/teacher/team/capacity", (r) => r.fulfill({ json: { capacity: 22, used: 1, free: 21 } }))
  await page.route("**/api/teacher/team/assistants", (r) => r.fulfill({ json: { assistants: [] } }))
  await page.route("**/api/teacher/team/invites", (r) => r.fulfill({ json: { invites: [] } }))
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/teacher/team/seats/m1/scope", async (r) => {
    scopeBody = r.request().postDataJSON()
    await r.fulfill({ json: seat })
  })
  await page.route("**/api/teacher/team/members/m1/cap", (r) => r.fulfill({ json: seat }))
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher/, { timeout: 15_000 })

  await page.goto("/teacher/team")
  await expect(page.getByText("1 of 22 seats used")).toBeVisible()
  await page.getByRole("button", { name: "Edit seat for Omar Hassan" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("Weekly study plans")).not.toBeChecked()
  await dialog.getByLabel("Weekly study plans").check()
  await dialog.getByRole("button", { name: "Save seat" }).click()
  await expect(dialog).toBeHidden()
  expect(scopeBody).toEqual({ subjects: ["0580"], actions: ["mark_paper", "study_plan"] })
})
