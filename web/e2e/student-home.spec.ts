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
  await expect(main.getByText("35 out of 40. That's an A. Q3 is the one to fix.")).toBeVisible({ timeout: 15_000 })
  await main.getByRole("button", { name: "Not now" }).click()
  await expect(main.getByText(/35 out of 40/)).toHaveCount(0)
  // Falls to the next fallback stage: the win-back line if the seed has one, else the default scan line.
  await expect(main.getByText(/Nothing to win back yet\. Scan your next paper\.|cost you \d+ marks last time/)).toBeVisible()
})
