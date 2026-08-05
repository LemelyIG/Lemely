import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { test, expect, type Page, type APIRequestContext } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/*
 * P2.5.5 screenshot corpus. Drives the four screens Phase 2.5 retrofitted
 * onto tokens + the component library (S-06 Overview, S-10/S-14 Correct a
 * paper, S-15/S-17 Paper result) against the real backend
 * (scripts/e2e_server.py — real Postgres/GoTrue/Storage, only Gemini-vision
 * mocked with the tests/golden/0625_m20_qp_12_mcq fixture) at three
 * breakpoints (380/768/1440). No dark mode — this product is single-theme.
 *
 * Kept separate from correct-paper.spec.ts / _smoke.spec.ts: this suite
 * captures a corpus rather than asserting product behaviour end to end, so
 * it can be re-run independently to regenerate reports/phase-2.5/screens/.
 *
 * NOTE on the "invalid file" error trigger for S-14/error: e2e_server.py
 * unconditionally monkeypatches `student.resolve_mark_scheme` /
 * `student.extract_answers` to return the golden fixture's data regardless
 * of what bytes are actually uploaded (and skips ScanMetadataExtractor
 * entirely since gemini_api_key is forced None) — so an invalid PDF/image
 * does NOT reach an error path in this harness; the marking pipeline
 * "succeeds" against any input. Instead this suite triggers the real,
 * deterministic 413 upload-cap error (lemely/web/upload_utils.py
 * MAX_UPLOAD_BYTES = 25 MiB) with an oversized file, which fails inside
 * CorrectPaper's own try/catch exactly like any other upload failure would.
 */

const BACKEND_URL = "http://127.0.0.1:8000"
const SCAN_PATH = path.resolve(
  __dirname,
  "../../tests/golden/0625_m20_qp_12_mcq/scan.pdf",
)
const SCREENS_DIR = path.resolve(__dirname, "../../reports/phase-2.5/screens")
const PASSWORD = "CorrectHorseBattery9!"

const BREAKPOINTS: { width: number; height: number }[] = [
  { width: 380, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]

function uniqueEmail(tag: string): string {
  return `e2e-shots-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

async function apiSignUp(request: APIRequestContext, email: string): Promise<void> {
  const res = await request.post(`${BACKEND_URL}/api/auth/signup`, {
    data: { email, password: PASSWORD, role: "student" },
  })
  expect(res.ok(), `signup failed: ${res.status()} ${await res.text()}`).toBeTruthy()
}

async function loginUI(page: Page, email: string): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(PASSWORD)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student/, { timeout: 15_000 })
}

/** Full-page capture at `reports/phase-2.5/screens/<screenId>/<state>--<bp>.png`. */
async function shoot(page: Page, screenId: string, state: string, bp: number): Promise<void> {
  const dir = path.join(SCREENS_DIR, screenId)
  fs.mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, `${state}--${bp}.png`), fullPage: true })
}

/** Collects console `error` messages and uncaught page errors so every test
 * can assert zero, per QUALITY-BAR.md's console-error gate. Excludes the
 * browser's own "Failed to load resource: ... 500/413" logging, which fires
 * for ANY non-2xx response — including the ones this suite deliberately
 * simulates to capture S-06/S-14's error states. That noise isn't a signal
 * of an app bug the way a React warning or an uncaught exception is. */
function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on("console", (msg) => {
    if (msg.type() === "error" && !/^Failed to load resource:/.test(msg.text())) {
      errors.push(`[console] ${msg.text()}`)
    }
  })
  page.on("pageerror", (err) => {
    errors.push(`[pageerror] ${err.message}`)
  })
  return errors
}

for (const bp of BREAKPOINTS) {
  test.describe(`screenshot corpus @${bp.width}`, () => {
    test(`S-10/S-14/S-15/S-17/S-06 flow @${bp.width}`, async ({ page, playwright }) => {
      test.setTimeout(120_000)
      const errors = watchConsole(page)
      await page.setViewportSize(bp)

      const request = await playwright.request.newContext()
      const email = uniqueEmail(`main-${bp.width}`)
      await apiSignUp(request, email)
      await request.dispose()
      await loginUI(page, email)

      // ── S-10 · Correct a paper — entry (default, nothing selected) ──────
      await page.goto("/student/correct")
      await expect(page.getByRole("heading", { name: /correct a paper/i })).toBeVisible()
      const markButton = page.getByRole("button", { name: /mark this paper/i })
      await expect(markButton).toBeDisabled()
      await shoot(page, "S-10", "default", bp.width)

      // ── S-10 · file-selected (golden fixture chosen, not yet submitted) ─
      await page.locator("#scan-file").setInputFiles(SCAN_PATH)
      await expect(markButton).toBeEnabled()
      await shoot(page, "S-10", "file-selected", bp.width)

      // ── S-14 · marking in progress (mid-flight, before it navigates away) ─
      await markButton.click()
      await expect(page.getByText(/marking now/i)).toBeVisible({ timeout: 5_000 })
      await shoot(page, "S-14", "marking-in-progress", bp.width)

      // ── S-15 · Paper result — collapsed default (marks/grade + question list) ─
      await expect(page).toHaveURL(/\/student\/result\//, { timeout: 30_000 })
      await expect(page.getByLabel("5 out of 8 marks, 63 percent")).toBeVisible()
      const questionRows = page.getByRole("button", {
        name: /^\d+ (Correct|Partial credit|Incorrect)\./,
      })
      await expect(questionRows).toHaveCount(8)
      await shoot(page, "S-15", "default", bp.width)

      // ── S-17 · Question detail (expand one row inline) ──────────────────
      await page.getByRole("button", { name: "Expand question detail" }).first().click()
      await expect(page.getByRole("button", { name: "Collapse question detail" }).first())
        .toBeVisible()
      await shoot(page, "S-17", "expanded", bp.width)

      // ── S-06 · Overview — default (this student now has one corrected paper) ─
      await page.goto("/student")
      await expect(page.getByText("Loading overview…")).toHaveCount(0, { timeout: 15_000 })
      await expect(page.getByRole("heading", { name: /good afternoon/i })).toBeVisible()
      await expect(page.getByText("Subjects this session")).toBeVisible()
      await shoot(page, "S-06", "default", bp.width)

      // ── S-06 · loading (delay the overview fetch to catch the pending state) ─
      await page.route("**/api/student/overview", async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 1_500))
        try {
          await route.continue()
        } catch {
          // React.StrictMode double-invokes the mount effect in dev, which
          // aborts the first overview fetch on remount; that request's
          // route resolves (as aborted) before this delayed continue()
          // runs. Benign — the second, real request gets its own route
          // invocation and completes normally.
        }
      })
      const reloadPromise = page.reload()
      await expect(page.getByText("Loading overview…")).toBeVisible({ timeout: 5_000 })
      await shoot(page, "S-06", "loading", bp.width)
      await reloadPromise
      await page.unroute("**/api/student/overview")

      // ── S-06 · error (force the overview fetch to fail) ─────────────────
      await page.route("**/api/student/overview", (route) =>
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Simulated failure for screenshot capture" }),
        }),
      )
      await page.reload()
      await expect(page.getByText("Couldn't load your overview")).toBeVisible({ timeout: 5_000 })
      await shoot(page, "S-06", "error", bp.width)
      await page.unroute("**/api/student/overview")

      // ── S-14 · error (real 413 upload-cap failure — see file header note) ─
      await page.goto("/student/correct")
      const oversized = Buffer.alloc(26 * 1024 * 1024, 1)
      await page.locator("#scan-file").setInputFiles({
        name: "oversized-scan.pdf",
        mimeType: "application/pdf",
        buffer: oversized,
      })
      const markButton2 = page.getByRole("button", { name: /mark this paper/i })
      await expect(markButton2).toBeEnabled()
      await markButton2.click()
      await expect(page.getByText(/marking stopped/i)).toBeVisible({ timeout: 20_000 })
      await shoot(page, "S-14", "error", bp.width)

      expect(errors, `console/page errors during capture: ${JSON.stringify(errors, null, 2)}`)
        .toEqual([])
    })

    test(`S-06 empty state @${bp.width}`, async ({ page, playwright }) => {
      const errors = watchConsole(page)
      await page.setViewportSize(bp)

      const request = await playwright.request.newContext()
      const email = uniqueEmail(`empty-${bp.width}`)
      await apiSignUp(request, email)
      await request.dispose()
      await loginUI(page, email)

      await expect(page.getByText("Loading overview…")).toHaveCount(0, { timeout: 15_000 })
      await expect(
        page.getByText("Correct your first paper to see it here"),
      ).toBeVisible()
      await shoot(page, "S-06", "empty", bp.width)

      expect(errors, `console/page errors during capture: ${JSON.stringify(errors, null, 2)}`)
        .toEqual([])
    })
  })
}
