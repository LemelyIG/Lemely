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
  // P3.3 replaced the "Loading overview…" text with layout-matching
  // skeletons, which announce themselves as a `status` region named
  // "Loading" instead of rendering that string.
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
    timeout: 15_000,
  })
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

  /*
   * P5.11: XP accrual, asserted on the same correction rather than in a spec
   * of its own — `POST /student/correct` is the `paper_corrected` award seam,
   * so a separate driver would only duplicate this journey.
   *
   * This account is signed up fresh in `beforeAll` and has corrected exactly
   * one paper, so the expected number is exact rather than a range: 50, the
   * whole of XP_AMOUNTS[paper_corrected], one award, far under both the 5/day
   * source cap and the 250/day global cap.
   *
   * Worth stating plainly, because it is the reason not to "simplify" this
   * into a smoke check: XP is awarded through `award_xp_safely`, which is
   * deliberately FAIL-OPEN (D5.1 §3 — an already-committed student action
   * must never be turned into an error response). `xp_events.subject_code` is
   * a live FK to `subjects.code`, and an unknown code raises inside that
   * helper and is swallowed. So if the seed ever stops producing the subject
   * row, the student silently loses the XP while the correction, this result
   * screen and every other gate in the build stay green. This assertion is
   * the only thing in the suite that would catch a fail-open seam failing.
   */
  await page.goto("/student/profile")
  // Since P5.11 the label/value pairs are named groups — the value used to be
  // a bare <div> sibling of its <Eyebrow>, with no accessible name and no
  // association, so there was nothing here to assert on.
  await expect(page.getByRole("group", { name: "Total XP" })).toContainText("50", {
    timeout: 15_000,
  })
  await expect(page.getByRole("group", { name: "Day streak" })).toContainText("1")

  /*
   * P5.11: the notification half of the same seam. `grade_ready` fires on this
   * same POST, so "push delivery" costs one navigation here rather than a
   * driver of its own.
   *
   * The row is the assertable fact and a delivered push is not: this machine
   * has no VAPID keys, so the transport reports itself unavailable by design
   * (D5.9 §4) and `notify_safely` returns
   * push_suppressed_reason="transport_unavailable" AFTER writing the row.
   * No prefs seeding is needed either — a user with no stored preferences row
   * reads DEFAULTS, which is every type enabled.
   */
  await page.goto("/student/notifications")
  await expect(
    page.getByRole("heading", { name: "Your paper has been marked" }),
  ).toBeVisible({ timeout: 15_000 })

  // Assert the ABSENCE of an Open button, and do not let a later session
  // "fix" it into a link. `grade_ready`'s payload carries the upload UUID, but
  // /student/result/:paperId addresses papers by history index and 404s on a
  // UUID — there is no route mapping an upload id to its result, so an Open
  // button here would be a guaranteed dead link. `destinationFor` returns null
  // for every type but `announcement`, which is that finding honoured in the
  // UI rather than worked around.
  await expect(page.getByRole("button", { name: "Open" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Mark as read" })).toBeVisible()
})
