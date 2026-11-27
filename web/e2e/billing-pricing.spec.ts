import { test, expect } from "@playwright/test"

// Wire shape: plan 02 `PublicCatalogueDTO` (no ids, no auth).
const student = {
  audience: "student",
  planTiers: [{ code: "student_plus_m", name: "Student Plus", audience: "student", interval: "monthly", priceMinor: 25000, currency: "EGP", features: { "Mark past papers": true }, includedSeats: null, extraSeatPriceMinor: null }],
  creditPacks: [{ code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}
const teacher = {
  audience: "teacher",
  planTiers: [{ code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "monthly", priceMinor: 90000, currency: "EGP", features: {}, includedSeats: 20, extraSeatPriceMinor: 3000 }],
  creditPacks: [],
}

test("public pricing switches audience and sends a choice through sign-in with the tier code", async ({ page }) => {
  await page.route("**/api/billing/public-catalogue?audience=student", (r) => r.fulfill({ json: student }))
  await page.route("**/api/billing/public-catalogue?audience=teacher", (r) => r.fulfill({ json: teacher }))
  await page.goto("/pricing")
  await expect(page.getByRole("heading", { level: 1, name: "Pricing" })).toBeVisible()
  await expect(page.getByText("Student Plus")).toBeVisible()
  await page.getByRole("radio", { name: "Teachers" }).click()
  await expect(page.getByText("20 student seats included")).toBeVisible()
  await page.getByRole("link", { name: "Choose Teacher Pro" }).click()
  await expect(page).toHaveURL(/\/login\?next=/)
  expect(decodeURIComponent(new URL(page.url()).searchParams.get("next") ?? "")).toBe(
    "/teacher/billing/plans?plan=teacher_pro_m&interval=month",
  )
})

test("a rate-limited catalogue shows the countdown", async ({ page }) => {
  await page.route("**/api/billing/public-catalogue**", (r) =>
    r.fulfill({ status: 429, headers: { "Retry-After": "20" }, json: { detail: "Too many requests" } }),
  )
  await page.goto("/pricing")
  await expect(page.getByText(/Try again in \d+ seconds\./)).toBeVisible()
  await expect(page.getByRole("button", { name: "Try again" })).toBeDisabled()
})
