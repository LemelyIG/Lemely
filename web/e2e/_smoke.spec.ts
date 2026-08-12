import { test, expect } from "@playwright/test"

test("chromium launches headless in this sandbox", async ({ page }) => {
  await page.setContent("<h1>hi</h1>")
  await expect(page.locator("h1")).toHaveText("hi")
})
