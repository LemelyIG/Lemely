import { test, expect, type Locator, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * L9 · the study plan's happy path on the account the seed gives a real
 * week (`practice.students.active`, enrolled in 0625, one weak topic).
 * The seed builds its plan on the real clock, so the week starts today.
 *
 * State is shared. `phase4-journey.spec.ts` reads this same account, and the
 * tests below mark a session done and move another, and CI retries a failed
 * test on the same database. So no test pins a row by position or expects a
 * session to still be open on a first look: rows are found by role and name,
 * and "open" means the row's name does not start with the screen-reader
 * prefix `Done: ` that `SessionRow` puts on a finished one.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

/**
 * A session row is the one button whose name carries `subject · activity · N min`
 * (`SessionRow`). The week strip's day buttons ("Tue 24: 2 sessions") and the
 * subject tabs never carry that shape, so they are not mistaken for rows.
 */
const ROW_NAME = /^.+ · .+ · \d+ (?:min|h)\b/
const OPEN_ROW_NAME = /^(?!Done: ).+ · .+ · \d+ (?:min|h)\b/

const sessionRows = (page: Page): Locator => page.getByRole("button", { name: ROW_NAME })
const openRows = (page: Page): Locator => page.getByRole("button", { name: OPEN_ROW_NAME })

/** The server's own "now" decides today's heading, so wait on the shape, not a weekday. */
async function expectPlanLoaded(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: /^Today · / })).toBeVisible({ timeout: 15_000 })
}

test("phone · today first, open a session, mark it done", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  await expectPlanLoaded(page)
  await expect(
    page.getByText(new RegExp(`\\d+ of ${seed.studyPlan.activeSessionCount} done`)).first(),
  ).toBeVisible()

  // The seeded weak topic is in the week, whether or not an earlier run finished it.
  await expect(
    sessionRows(page).filter({ hasText: new RegExp(escapeRe(seed.studyPlan.activeSessionTopic)) }).first(),
  ).toBeVisible()

  await openRows(page).first().click()
  const sheet = page.getByRole("dialog")
  await expect(sheet.getByText("Why this?")).toBeVisible()
  await expect(page).toHaveURL(/\/student\/plan\/session\//)

  await sheet.getByRole("button", { name: "Mark done" }).click()
  await expect(sheet.getByText("Done", { exact: true })).toBeVisible()

  // Back closes the sheet and lands on the list it was opened from.
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await expect(page).toHaveURL(/\/student\/plan$/)
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("phone · a deep link opens the sheet, and an unknown id says so", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  // Opens on a done session as readily as on an open one, so a prior run cannot break it.
  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}/session/${seed.studyPlan.activeSessionId}`)
  await expect(page.getByRole("dialog").getByText("Why this?")).toBeVisible({ timeout: 15_000 })

  // An id that is not in this week says so, and is not an error.
  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}/session/00000000-0000-4000-8000-000000000000`)
  await expect(page.getByText("That session isn’t in this week’s plan.")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("phone · move an open session to a later day", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  await expectPlanLoaded(page)
  await openRows(page).first().click()
  const sheet = page.getByRole("dialog")
  await expect(sheet.getByText("Why this?")).toBeVisible()

  const moveButton = sheet.getByRole("button", { name: "Move", exact: true })
  // The server decides "today", so the browser clock cannot be pinned. What can be read is its
  // weekday. Only on a Sunday (the plan's last day) may the control be missing, and then the test
  // says so; on any other day its absence is a failure, never a pass.
  const heading = (await page.getByRole("heading", { name: /^Today · / }).textContent()) ?? ""
  const lastDay = /Sunday/.test(heading)
  if (!lastDay) await expect(moveButton).toHaveCount(1)

  if ((await moveButton.count()) === 0) {
    test.info().annotations.push({ type: "note", description: "Sunday: no later day to move to" })
    await expect(moveButton).toHaveCount(0)
  } else {
    await moveButton.click()
    const target = sheet.getByRole("group", { name: "Move to" }).getByRole("button").last()
    const label = ((await target.textContent()) ?? "").trim()
    expect(label).not.toBe("")
    await target.click()
    const toast = label === "Today" ? "Moved to today" : `Moved to ${label}`
    await expect(page.getByText(toast).first()).toBeVisible()
  }
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})

test("desktop · list with a side panel that follows the row", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 1280, height: 820 })
  await asStudent(page, seed.practice.students.active)

  await page.goto("/student/plan")
  await expectPlanLoaded(page)
  const panel = page.getByRole("complementary", { name: "Session" })
  await expect(page.getByRole("dialog")).toHaveCount(0)

  // Choosing a row moves the panel to it and puts the session in the url.
  const topic = new RegExp(escapeRe(seed.studyPlan.activeSessionTopic))
  await sessionRows(page).filter({ hasText: topic }).first().click()
  await expect(panel.getByText("Why this?")).toBeVisible({ timeout: 15_000 })
  await expect(panel.getByRole("heading", { level: 2, name: topic })).toBeVisible()
  await expect(page).toHaveURL(/\/student\/plan\/session\//)
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
})
