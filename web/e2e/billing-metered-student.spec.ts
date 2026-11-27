import { test, expect, type Page } from "@playwright/test"
import { readSeed } from "./seed"

async function login(page: Page) {
  const student = readSeed().students.control
  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
}

// Wire shapes: plan 05 `BillingSummaryDTO`, plan 04 `EstimateDTO`, plan 04's flat 402 body.
const summary = {
  beneficiary: { userId: "u", displayName: "S", audience: "student" },
  subscription: null, canManage: true, managedByName: null, savedCard: null,
  usage: { fraction: null, resetsAt: null }, credits: { totalUnits: 0, expiring: [] }, debtUnits: 0, seats: null,
}
const estimate = (over: Record<string, unknown>) => ({
  low: 3, high: 5, payer: "credits", percentLow: null, percentHigh: null, blockedReason: null, ...over,
})
const pdf = { name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") }

test("the marking screen shows the estimate, then a 402 as a buy-credits notice", async ({ page }) => {
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/usage/estimate", (r) => r.fulfill({ json: estimate({}) }))
  await page.route("**/api/student/uploads", (r) =>
    r.fulfill({ status: 402, json: { error: "usage_blocked", reason: "insufficient_credits", estimate: [3, 5] } }),
  )
  await login(page)
  await page.goto("/student/correct")
  await page.locator('input[type="file"]').first().setInputFiles(pdf)
  await expect(page.getByTestId("estimate-range")).toContainText("3–5 credits")
  await page.getByRole("button", { name: "Mark this paper" }).click()
  const notice = page.getByTestId("usage-blocked-notice")
  await expect(notice).toHaveAttribute("data-reason", "insufficient_credits")
  await expect(notice.getByRole("link", { name: "Buy credits" })).toHaveAttribute("href", "/student/billing/plans#packs")
  await expect(page.getByRole("button", { name: "Mark this paper" })).toBeDisabled()
})

test("a blocked estimate disables the start control before any upload", async ({ page }) => {
  let uploads = 0
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/usage/estimate", (r) => r.fulfill({ json: estimate({ blockedReason: "no_active_plan" }) }))
  await page.route("**/api/student/uploads", (r) => {
    uploads += 1
    return r.abort()
  })
  await login(page)
  await page.goto("/student/correct")
  await page.locator('input[type="file"]').first().setInputFiles(pdf)
  await expect(page.getByTestId("usage-blocked-notice")).toHaveAttribute("data-reason", "no_active_plan")
  await expect(page.getByRole("button", { name: "Mark this paper" })).toBeDisabled()
  expect(uploads).toBe(0)
})
