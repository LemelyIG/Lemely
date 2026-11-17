import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

async function login(page: Page) {
  const { teacher } = readSeed()
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })
}

/** Intercepts the decision POST so the seeded rows stay open for every other spec. */
async function interceptResolve(page: Page): Promise<string[]> {
  const posts: string[] = []
  await page.route("**/api/teacher/review/*/resolve", async (route) => {
    posts.push(route.request().url())
    const id = route.request().url().split("/").at(-2)
    await route.fulfill({ json: { itemId: id, status: "resolved", studentId: null, classId: null } })
  })
  return posts
}

test("a teacher sorts, opens, re-marks, undoes and accepts an answer", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  const errors = watchConsole(page)
  const { reviewItem } = readSeed()
  await login(page)

  // The decision is intercepted: the seeded rows stay open for every other spec.
  const posts = await interceptResolve(page)

  await page.goto("/teacher/review")
  await expect(page.getByRole("heading", { level: 1 })).toContainText("left")
  await page.getByRole("button", { name: "Marks lost" }).click()
  await page.getByRole("menuitemradio", { name: "Confidence" }).click()
  await expect(page).toHaveURL(/sort=confidence/)

  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/teacher/review/${reviewItem.itemId}`))
  const panel = page.getByRole("article")
  await expect(panel.getByRole("group", { name: "Marking points" }).getByTestId("marker-verdict-row")).toHaveCount(3)

  // Untick an awarded point: the action turns into Save.
  const awarded = panel.getByTestId("marker-verdict-row").and(page.locator('[aria-pressed="true"]')).first()
  await awarded.click()
  await expect(panel.getByRole("button", { name: /^Save \d+\/\d+$/ })).toBeVisible()
  await expect(panel.getByText(/−1 from Lemely/)).toBeVisible()

  // Decide, then undo inside the window: nothing is sent.
  await panel.getByRole("button", { name: /^Save/ }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).toHaveAttribute("data-gone", "")
  await page.getByRole("button", { name: "Undo" }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).not.toHaveAttribute("data-gone", "")
  expect(posts).toEqual([])

  // Decide again and let the window pass: exactly one POST.
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await page.getByRole("article").getByRole("button", { name: /^(Accept|Save)/ }).click()
  await expect.poll(() => posts.length, { timeout: 8_000 }).toBe(1)

  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("a pending decision is held for the undo window, then flushed when the teacher leaves the page", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  const errors = watchConsole(page)
  const { reviewItem } = readSeed()
  await login(page)
  const posts = await interceptResolve(page)

  await page.goto("/teacher/review")
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await page.getByRole("article").getByRole("button", { name: /^(Accept|Save)/ }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).toHaveAttribute("data-gone", "")

  // Inside the 5s window nothing has been sent.
  await page.waitForTimeout(1_500)
  expect(posts).toEqual([])

  // Leaving the screen (an in-app navigation unmounts the queue) sends it at once, long before 5s.
  const decidedAt = Date.now()
  await page.getByRole("link", { name: "Overview", exact: true }).first().click()
  await expect(page).toHaveURL(/\/teacher$/)
  await expect.poll(() => posts.length, { timeout: 3_000 }).toBe(1)
  expect(Date.now() - decidedAt).toBeLessThan(4_000)

  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("closing the tab (pagehide) flushes a pending decision before the undo window ends", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  const { reviewItem } = readSeed()
  await login(page)
  const posts = await interceptResolve(page)

  await page.goto("/teacher/review")
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await page.getByRole("article").getByRole("button", { name: /^(Accept|Save)/ }).click()
  await expect(page.locator(`[data-review-row="${reviewItem.itemId}"]`)).toHaveAttribute("data-gone", "")
  await page.waitForTimeout(1_000)
  expect(posts).toEqual([])

  // A full document navigation fires `pagehide`; the keepalive request is what carries the decision out.
  const sent = page.waitForRequest((r) => /\/review\/[^/]+\/resolve$/.test(r.url()), { timeout: 4_000 })
  const decidedAt = Date.now()
  await page.goto("/teacher/classes")
  await sent
  expect(Date.now() - decidedAt).toBeLessThan(4_000)
})

test("on a phone an answer opens full screen and Queue goes back", async ({ page }, info) => {
  test.skip(info.project.name !== "iphone-15", "phone layout")
  const { reviewItem } = readSeed()
  await login(page)
  await page.goto("/teacher/review")
  await page.locator(`[data-review-row="${reviewItem.itemId}"]`).click()
  await expect(page.getByRole("button", { name: "Back to the queue" })).toBeVisible()
  await expect(page.getByRole("region", { name: "Review queue" })).toHaveCount(0)
  await page.getByRole("button", { name: "Back to the queue" }).click()
  await expect(page).toHaveURL(/\/teacher\/review(\?|$)/)
})

test("filters live in the URL and Clear filters resets them", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium", "desktop layout")
  await login(page)
  await page.goto("/teacher/review?q=zzzz-no-such-student")
  await expect(page.getByText("No answers match these filters.")).toBeVisible()
  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page).not.toHaveURL(/q=/)
})
