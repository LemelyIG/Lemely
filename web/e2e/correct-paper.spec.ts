import path from "node:path"
import { fileURLToPath } from "node:url"
import { test, expect, type APIRequestContext } from "@playwright/test"
import { screensDir } from "./report-dir"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/*
 * P2.10 acceptance: full student journey against the real backend (real
 * Postgres/GoTrue/Storage via scripts/e2e_server.py, Gemini-vision mocked
 * with the tests/golden/0625_m20_qp_12_mcq fixture) — signup (API), login
 * (real UI), upload+mark a scan, and verify the result screen renders the
 * deterministic ground truth (5/8, 8 question cards).
 */

const BACKEND_URL = "http://127.0.0.1:8000"
const SCAN_PATH = path.resolve(
  __dirname,
  "../../tests/golden/0625_m20_qp_12_mcq/scan.pdf",
)
const SCREENS_DIR = screensDir()

const email = `e2e-${Date.now()}@example.com`
const password = "CorrectHorseBattery9!"

test.beforeAll(async ({ playwright }) => {
  const request: APIRequestContext = await playwright.request.newContext()
  const res = await request.post(`${BACKEND_URL}/api/auth/signup`, {
    data: { email, password, role: "student" },
  })
  expect(res.ok(), `signup failed: ${res.status()} ${await res.text()}`).toBeTruthy()
  await request.dispose()
})

test("student can log in, upload a scan, and see the marked result", async ({ page }) => {
  await page.goto("/login")
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: /sign in/i }).click()

  await expect(page).toHaveURL(/\/student/, { timeout: 15_000 })
  await expect(page.getByText("Loading overview…")).toHaveCount(0, { timeout: 15_000 })
  await page.screenshot({
    path: path.join(SCREENS_DIR, "p2.10-01-student-dashboard.png"),
    fullPage: true,
  })

  await page.goto("/student/correct")
  await page.locator("#scan-file").setInputFiles(SCAN_PATH)

  const markButton = page.getByRole("button", { name: /mark this paper/i })
  await expect(markButton).toBeEnabled()
  await markButton.click()

  await expect(page).toHaveURL(/\/student\/result\//, { timeout: 30_000 })

  // Marks: {awarded}/{max} — deterministic ground truth from the golden
  // fixture (5/8), not a fuzzy accuracy metric. Since the P2.5.4 retrofit
  // this is the hero MarkDisplay (C-2), which carries the value in its own
  // aria-label rather than a sibling text node — assert on that.
  await expect(page.getByLabel("5 out of 8 marks, 63 percent")).toBeVisible()

  // Predicted grade: real boundary-lookup logic, just assert non-empty.
  // Since P2.5.4 this is the GradeBadge (C-1), role="img" with the grade in
  // its aria-label ("Predicted grade B").
  const gradeBadge = page.getByRole("img", { name: /^Predicted grade / })
  const gradeText = await gradeBadge.getAttribute("aria-label")
  expect(gradeText).toMatch(/^Predicted grade [A-Z*]+$/)

  // 8 question rows, ids "1".."8" — since P2.5.4 each is a QuestionRow (C-6)
  // toggle button whose accessible name starts with "{number} {state label}."
  // (see QuestionRow in components/ui/question-row.tsx), not a bare div.
  const questionRows = page.getByRole("button", {
    name: /^\d+ (Correct|Partial credit|Incorrect)\./,
  })
  await expect(questionRows).toHaveCount(8)
  const names = await questionRows.allInnerTexts()
  const ids = names.map((n) => n.match(/^\d+/)?.[0]).sort()
  expect(ids).toEqual(["1", "2", "3", "4", "5", "6", "7", "8"])

  await page.screenshot({
    path: path.join(SCREENS_DIR, "p2.10-02-paper-result.png"),
    fullPage: true,
  })
})
