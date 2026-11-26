import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

test("the grading console blocks an upload the balance cannot cover", async ({ page }) => {
  const teacher = readSeed().teacher
  let uploads = 0
  await page.route("**/api/usage/estimate", (r) =>
    r.fulfill({
      json: { low: 3, high: 5, payer: "none", percentLow: null, percentHigh: null, blockedReason: "outstanding_debt" },
    }),
  )
  await page.route("**/api/papers/upload", (r) => {
    uploads += 1
    return r.abort()
  })
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher/, { timeout: 15_000 })

  await page.goto("/teacher/grading")
  await page.locator('input[type="file"]').first().setInputFiles({ name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") })
  const notice = page.getByTestId("usage-blocked-notice")
  await expect(notice).toHaveAttribute("data-reason", "outstanding_debt")
  await expect(notice).toContainText("Balance below zero")
  expect(uploads).toBe(0)
})
