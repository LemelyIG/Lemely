import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

// Wire shapes: plan 07 `ProblemQueueDTO`, `AdminPaymentsPageDTO`, `AdminPaymentRowDTO`.
const stale = {
  id: "pay7", payerUserId: "u1", beneficiaryUserId: "u2", purpose: "credit_pack", status: "pending", amountMinor: 15000,
  currency: "EGP", refundedMinor: 0, paymobOrderId: "PM-7", paymobTxnId: null, planTierId: null, creditPackId: "p1",
  subscriptionId: null, seatQuantity: null, createdAt: "2026-11-05T08:00:00Z", paidAt: null, refunds: [],
}

test("a platform admin sees the problem queue and must give a reason to reconcile", async ({ page }) => {
  const admin = readSeed().tutoring.platformAdmin
  let reconcileBody: unknown = null
  await page.route("**/api/admin/billing/problems", (r) =>
    r.fulfill({ json: { mismatches: [], stalePending: [stale], missingCallbacks: [], hmacFailures: [], hmacFailures24h: 0, refundsNeedingAttention: [] } }),
  )
  await page.route("**/api/admin/billing/payments**", (r) => r.fulfill({ json: { items: [], nextCursor: null } }))
  await page.route("**/api/admin/billing/payments/pay7/reconcile", async (r) => {
    reconcileBody = r.request().postDataJSON()
    await r.fulfill({ json: { ...stale, status: "paid" } })
  })
  await page.goto("/login")
  await page.getByLabel("Email").fill(admin.email)
  await page.getByLabel("Password").fill(admin.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/platform/, { timeout: 15_000 })

  await page.goto("/platform/billing/payments")
  await expect(page.getByRole("heading", { name: "Pending over an hour" })).toBeVisible()
  await page.getByRole("button", { name: "Reconcile order PM-7" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Reconcile", exact: true }).click()
  // The refusal sits on the Reason field, which takes focus.
  await expect(dialog.getByText("Give a reason of at least 5 characters.")).toBeVisible()
  await expect(dialog.getByLabel("Reason")).toBeFocused()
  expect(reconcileBody).toBeNull()
  await dialog.getByLabel("Reason").fill("callback never arrived")
  await dialog.getByRole("button", { name: "Reconcile", exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(reconcileBody).toEqual({ reason: "callback never arrived" })
  await expect(page.getByRole("status").filter({ hasText: "Checked with Paymob. Order PM-7 is paid." })).toBeVisible()
})

test("a payments read that fails is an error, never a clear queue", async ({ page }) => {
  const admin = readSeed().tutoring.platformAdmin
  await page.route("**/api/admin/billing/problems", (r) => r.fulfill({ status: 500, json: { detail: "boom" } }))
  await page.route("**/api/admin/billing/payments**", (r) => r.fulfill({ json: { items: [], nextCursor: null } }))
  await page.goto("/login")
  await page.getByLabel("Email").fill(admin.email)
  await page.getByLabel("Password").fill(admin.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/platform/, { timeout: 15_000 })

  await page.goto("/platform/billing/payments")
  await expect(page.getByText("Couldn't load the problem queue")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("No payment problems right now.")).toHaveCount(0)
})
