import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { test, expect, type Page, type APIRequestContext } from "@playwright/test"
import { screensDir } from "./report-dir"
import { watchConsole } from "./console-errors"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/*
 * P2.5.5 screenshot corpus. Drives the four screens Phase 2.5 retrofitted
 * onto tokens + the component library (S-06 Overview, S-10/S-14 Correct a
 * paper, S-15/S-17 Paper result) against the real backend
 * (scripts/e2e_server.py — real Postgres/GoTrue/Storage, only Gemini-vision
 * mocked with the tests/golden/0625_m20_qp_12_mcq fixture) at three
 * breakpoints (380/768/1440). Light only, by design: dark mode shipped in
 * C5, but its captures live in `scripts/audit.mjs` (five named
 * `*-dark` states, Puppeteer's `emulateMediaFeatures`), not here. Keeping
 * this Playwright corpus light-only means every baseline in it stays a
 * stable pixel diff across a run — a corpus that alternated light/dark
 * per screen would double as an implicit "did the theme also change"
 * assertion nobody asked this suite to make.
 *
 * Kept separate from correct-paper.spec.ts / _smoke.spec.ts: this suite
 * captures a corpus rather than asserting product behaviour end to end, so
 * it can be re-run independently to regenerate a phase's screens/ corpus
 * (see report-dir.ts — set LEMELY_REPORT_DIR to re-baseline a phase).
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
const SCREENS_DIR = screensDir()
const PASSWORD = "CorrectHorseBattery9!"

const BREAKPOINTS: { width: number; height: number }[] = [
  { width: 380, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]

function uniqueEmail(tag: string): string {
  return `e2e-shots-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

interface SignedUpAccount {
  accessToken: string
  /** `/verify-email/<token>` — see `apiVerifyEmail` for why this suite redeems
   * it directly rather than through the dev-link UI. */
  devLink: string | null
}

/** Returns the fresh account's access token (and dev verification link), so
 * the caller can also drive `apiCompleteOnboarding` / `apiVerifyEmail` below
 * without a second sign-in round trip. */
async function apiSignUp(request: APIRequestContext, email: string): Promise<SignedUpAccount> {
  const res = await request.post(`${BACKEND_URL}/api/auth/signup`, {
    data: { email, password: PASSWORD, role: "student", acceptedTerms: true },
  })
  expect(res.ok(), `signup failed: ${res.status()} ${await res.text()}`).toBeTruthy()
  const { accessToken, devLink } = (await res.json()) as {
    accessToken: string
    devLink: string | null
  }
  return { accessToken, devLink }
}

/*
 * D7.5's gate (`canStartRun`, `web/src/lib/uploadRun.ts`) refuses to start a
 * marking run for an unverified email — and a freshly signed-up account is
 * unverified by construction, so this corpus's own "Mark this paper" click
 * would otherwise never leave a disabled button. Verifying through the real
 * `/verify-email/:token` UI (as `signup.spec.ts` does, because that IS what
 * it tests) would capture a screen this corpus doesn't own, so this redeems
 * `devLink` — the exact token the UI's link carries, minted by
 * `AuthService.signup` for local/test environments (spec §4.4, D7.4/D7.6/
 * D7.7) — straight against the same public endpoint the link's page calls
 * (`POST /api/auth/verify-email`, `lemely/web/routers/auth.py`).
 */
async function apiVerifyEmail(request: APIRequestContext, devLink: string | null): Promise<void> {
  expect(devLink, "signup did not mint a dev verification link").not.toBeNull()
  const token = devLink!.split("/").pop()
  const res = await request.post(`${BACKEND_URL}/api/auth/verify-email`, {
    data: { token },
  })
  expect(res.ok(), `verify-email failed: ${res.status()} ${await res.text()}`).toBeTruthy()
}

/*
 * D7.9's onboarding gate (`studentOnboardingRedirect`,
 * `web/src/portals/student/index.tsx`) sends any student whose profile has
 * no `onboardingCompletedAt` to `/student/onboard` on every navigation,
 * including the very first one after signup — this corpus's freshly minted
 * accounts are no exception. Driving the wizard through the real UI would
 * capture screens this corpus doesn't own (S-01/S-02, `phase4-journey.spec.ts`'s
 * job), so this calls the same completion endpoint the wizard itself calls
 * (`POST /api/me/student-profile/complete-onboarding`,
 * `lemely/web/routers/me.py`) directly, which needs no prior subject
 * enrolment — matching this suite's own scope of "reach /student/correct",
 * not "onboard a student".
 */
async function apiCompleteOnboarding(request: APIRequestContext, accessToken: string): Promise<void> {
  const res = await request.post(`${BACKEND_URL}/api/me/student-profile/complete-onboarding`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  expect(res.ok(), `complete-onboarding failed: ${res.status()} ${await res.text()}`).toBeTruthy()
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

for (const bp of BREAKPOINTS) {
  test.describe(`screenshot corpus @${bp.width}`, () => {
    test(`S-10/S-14/S-15/S-17/S-06 flow @${bp.width}`, async ({ page, playwright }) => {
      test.setTimeout(120_000)
      const errors = watchConsole(page)
      await page.setViewportSize(bp)

      const request = await playwright.request.newContext()
      const email = uniqueEmail(`main-${bp.width}`)
      const account = await apiSignUp(request, email)
      await apiCompleteOnboarding(request, account.accessToken)
      // Unlike the empty-state flow below, this one submits a real marking
      // run — D7.5's gate needs a verified email for that (see
      // `apiVerifyEmail`).
      await apiVerifyEmail(request, account.devLink)
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
      // P3.3 replaced the "Loading overview…" text with layout-matching
      // skeletons, which announce themselves as a `status` region named
      // "Loading" instead of rendering that string.
      await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
        timeout: 15_000,
      })
      // P3.2: the greeting follows the reader's real local time now, so a
      // fixed "afternoon" would fail this capture for most of the day.
      await expect(
        page.getByRole("heading", { name: /good (morning|afternoon|evening)/i }),
      ).toBeVisible()
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
      // This capture is the loading state itself, so it targets the
      // skeletons directly. `.first()` because the screen now renders
      // several status regions (header, ledger, two panels) rather than
      // the single line of text it used to.
      await expect(page.getByRole("status", { name: "Loading" }).first()).toBeVisible({
        timeout: 5_000,
      })
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
      const account = await apiSignUp(request, email)
      await apiCompleteOnboarding(request, account.accessToken)
      await request.dispose()
      await loginUI(page, email)

      // P3.3 replaced the "Loading overview…" text with layout-matching
      // skeletons, which announce themselves as a `status` region named
      // "Loading" instead of rendering that string.
      await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
        timeout: 15_000,
      })
      // P3.2 replaced S-06's single centred EmptyState with the composed
      // `GettingStarted` panel, so this asserts on the new heading. The
      // screenshot this gates is the first-run capture, which is exactly the
      // surface that changed, so the assertion has to move with it.
      await expect(page.getByText("Let's get your first paper marked")).toBeVisible()
      await shoot(page, "S-06", "empty", bp.width)

      expect(errors, `console/page errors during capture: ${JSON.stringify(errors, null, 2)}`)
        .toEqual([])
    })
  })
}
