import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * L4 · the Practice tab end to end on the seeded `practice.students.active`
 * account: tiles, win marks back, Recent with the unsubmitted set to resume,
 * the builder sheet with a live match count, and a created set.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

test("Practice tab · hub, builder sheet and a started set", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)
  await page.goto("/student/practice")

  for (const name of ["Practice set", "Flashcards", "Past papers", "Placement test"]) {
    await expect(page.getByText(name, { exact: true })).toBeVisible({ timeout: 15_000 })
  }
  // The seed's one deliberate wrong answer is a real weakness, so a topic is worth marks.
  await expect(page.getByText("Win marks back")).toBeVisible()
  await expect(page.getByText(/^\+\d+$/).first()).toBeVisible()
  // The seed's created-but-untouched set is the resume row.
  await expect(page.getByText("Resume", { exact: true })).toBeVisible()

  await page.getByText("Practice set", { exact: true }).click()
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet).toBeVisible()
  // The seed has six questions in each topic; one weak topic is preselected.
  await expect(sheet.getByRole("status")).toHaveText("Only 6 questions match. Add a topic or ask for fewer.", { timeout: 15_000 })

  const morePreview = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === `/api/student/practice/${seed.practice.subjectCode}/preview` && url.searchParams.get("count") === "15"
  })
  await sheet.getByRole("button", { name: "More" }).click()
  expect((await morePreview).ok()).toBeTruthy()
  await expect(sheet.getByRole("group", { name: "Questions" })).toContainText("15")

  // Changing the requested size alone does not change the matching pool.
  // Add a second seeded topic to prove the live match count changes from 6 to 12.
  await sheet.getByRole("switch", { name: "Weak topics only" }).click()
  const expandedPreview = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === `/api/student/practice/${seed.practice.subjectCode}/preview` &&
      url.searchParams.get("count") === "15" && url.searchParams.getAll("topics").length === 2
  })
  await sheet.getByRole("group", { name: "Topics" }).locator('button[aria-pressed="false"]').first().click()
  expect((await expandedPreview).ok()).toBeTruthy()
  await expect(sheet.getByRole("status")).toHaveText("Only 12 questions match. Add a topic or ask for fewer.", { timeout: 15_000 })

  await sheet.getByRole("button", { name: /^Start/ }).click()
  await expect(page).toHaveURL(/\/student\/practice\/set\/[0-9a-f-]+$/, { timeout: 15_000 })

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("Practice tab · past papers opens the paper sheet or the honest empty state", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)
  await page.goto("/student/practice/papers")

  const empty = page.getByText(/papers to print yet/)
  const firstRow = page.getByRole("listitem").filter({ hasText: /·/ }).first()
  await expect(empty.or(firstRow)).toBeVisible({ timeout: 15_000 })
  if (await firstRow.isVisible()) {
    await firstRow.click()
    await expect(page.getByRole("dialog")).toBeVisible()
    await expect(page.getByRole("button", { name: "Print paper" })).toBeVisible()
  }

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})
