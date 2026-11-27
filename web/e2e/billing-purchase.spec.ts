import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

// Wire shapes (plan 02 `CatalogueDTO`, plan 05 `BillingSummaryDTO`, plan 02 `PaymentStatusDTO`).
const catalogue = {
  planTiers: [
    { planTierId: "t1", code: "s_m", name: "Student Plus", priceMinor: 25000, currency: "EGP", interval: "monthly", audience: "student", includedSeats: 0, extraSeatPriceMinor: 0, features: { "Mark past papers": true } },
  ],
  creditPacks: [{ creditPackId: "p1", code: "pack_500", name: "500 credits", credits: 500, priceMinor: 15000, currency: "EGP" }],
}
const summary = {
  beneficiary: { userId: "u", displayName: "S", audience: "student" },
  subscription: null,
  canManage: true,
  managedByName: null,
  savedCard: null,
  usage: { fraction: null, resetsAt: null },
  credits: { totalUnits: 0, expiring: [] },
  debtUnits: 0,
  seats: null,
}

async function stubBilling(page: Page) {
  let polls = 0
  await page.route("**/api/billing/catalogue**", (r) => r.fulfill({ json: catalogue }))
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/billing/checkout/pack", (r) =>
    r.fulfill({ json: { paymentId: "pay-e2e", checkoutUrl: "/billing/return/pay-e2e" } }),
  )
  await page.route("**/api/billing/payments/pay-e2e", (r) => {
    polls += 1
    r.fulfill({
      json: {
        paymentId: "pay-e2e",
        status: polls < 2 ? "pending" : "paid",
        purpose: "credit_pack",
        amountMinor: 15000,
        currency: "EGP",
        description: "500 credits",
        paidAt: polls < 2 ? null : "2026-11-05T09:01:00Z",
      },
    })
  })
}

test("a student buys a credit pack and the return page confirms it by polling", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.control
  await stubBilling(page)

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await page.goto("/student/billing/plans")
  await expect(page.getByRole("heading", { name: "Credit packs" })).toBeVisible()
  await page.getByRole("button", { name: "Buy 500 credits" }).click()

  await expect(page).toHaveURL(/\/billing\/return\/pay-e2e$/)
  await expect(page.getByRole("status")).toContainText("Confirming your payment")
  await expect(page.getByRole("heading", { name: "Credits added" })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole("link", { name: "Back to billing" })).toHaveAttribute("href", "/student/billing")
  expect(errors).toEqual([])
})
