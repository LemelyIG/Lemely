import { expect, test } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/* The corrected-paper student has one 0625 paper and no 0580 papers. Both
 * subject states below come from real API round trips. */
test("a student with one paper sees the sparse path and opens the paper", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.correctedPaper
  expect(student.correctedPaperId).toBeTruthy()

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await page.goto("/student/subject/0625")
  await expect(page.getByRole("heading", { level: 2, name: /^Your path to / })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("group", { name: /^Paper 1 marks so far:/ })).toBeVisible()
  await expect(page.getByText("One step so far. Two more papers show your trend.")).toBeVisible()
  await expect(page.getByText("Great start. Next paper?")).toBeVisible()
  await expect(page.getByRole("link", { name: "Scan your next paper" })).toHaveAttribute("href", "/student/correct?subject=0625")
  await expect(page.getByRole("tablist", { name: "Choose a paper" })).toHaveCount(0)

  const papers = page.getByRole("list", { name: "Papers, newest first" })
  await expect(papers.getByRole("link")).toHaveCount(1)
  await papers.getByRole("link").click()
  await expect(page).toHaveURL(`/student/result/${student.correctedPaperId}`)

  await page.goto("/student/subject/0580")
  await expect(page.getByText("Let’s find your first step")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("link", { name: /^Scan a .+ paper$/ })).toHaveAttribute("href", "/student/correct?subject=0580")

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})
