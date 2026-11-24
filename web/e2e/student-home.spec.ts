import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

test("Home's doors go somewhere real, and Me opens its people doors", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.correctedPaper
  await injectSession(page, { accessToken: student.accessToken, userId: student.userId, role: "student" })

  await page.goto("/student")
  const main = page.getByRole("main")
  const floor = main.getByRole("navigation", { name: "Your grades" })
  await expect(floor).toBeVisible({ timeout: 15_000 })

  const action = main.getByTestId("home-stage-action").filter({ visible: true })
  await expect(action).toBeVisible()
  expect(await action.getAttribute("href")).toMatch(/^\/student\//)

  const subject = floor.getByRole("link").first()
  const href = await subject.getAttribute("href")
  await subject.click()
  await expect(page).toHaveURL(new RegExp(`${href}$`))

  await page.goto("/student/profile")
  await expect(main.getByText(/Level \d+ · /)).toBeVisible({ timeout: 15_000 })
  await main.getByRole("navigation", { name: "Your people" }).getByRole("link", { name: /Standings/ }).click()
  await expect(page).toHaveURL(/\/student\/board$/)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("Not now moves Binny on to the next suggestion", async ({ page }) => {
  const seed = readSeed()
  const student = seed.students.correctedPaper
  await injectSession(page, { accessToken: student.accessToken, userId: student.userId, role: "student" })
  await page.route("**/api/student/home", async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.moments = [
      {
        kind: "result", paperId: "0", subjectCode: "0625", subjectName: "Physics", paperNumber: 1,
        awarded: 35, maximum: 40, grade: "A", previousGrade: null, focusQuestion: "3",
        recordedAt: new Date().toISOString(),
      },
    ]
    await route.fulfill({ response, json: body })
  })
  await page.goto("/student")
  const main = page.getByRole("main")
  // The bubble is the one live paragraph in the Binny region. Other Home rows reuse words like "Scan your next paper".
  const line = main.getByRole("region", { name: "Binny" }).locator("p[aria-live='polite']")
  await expect(line).toHaveText("That's an A", { timeout: 15_000 })
  await expect(main.getByTestId("home-stage-action")).toHaveText("Fix Q3")
  await main.getByRole("button", { name: "Not now" }).click()
  await expect(line).not.toHaveText("That's an A")
  // Falls to the next fallback stage: the win-back line if the seed has one, else the default scan line.
  // The bubble is the line alone, no greeting before it.
  await expect(line).toHaveText(/^(Win marks back|Scan your next paper)$/)
})

test("Me's Standings door reads Rankings off for a student who turned rankings off, and opens the board", async ({ page }) => {
  const seed = readSeed()
  const student = seed.students.correctedPaper
  await injectSession(page, { accessToken: student.accessToken, userId: student.userId, role: "student" })
  await page.route("**/api/me/student-profile", async (route) => {
    if (route.request().method() !== "GET") return route.continue()
    const response = await route.fetch()
    const body = await response.json()
    body.profile.leaderboardOptOut = true
    await route.fulfill({ response, json: body })
  })
  await page.goto("/student/profile")
  const standings = page.getByRole("main").getByRole("navigation", { name: "Your people" }).getByRole("link", { name: /Standings/ })
  await expect(standings).toContainText("Rankings off", { timeout: 15_000 })
  await expect(standings).not.toContainText("Join a class")
  await expect(standings).toHaveAttribute("href", "/student/board")
  await standings.click()
  await expect(page).toHaveURL(/\/student\/board$/)
  await expect(page.getByRole("button", { name: "Show me again" })).toBeVisible()
})
