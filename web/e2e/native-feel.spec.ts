import { test, expect, type Page } from "@playwright/test"
import { failedRequests, interactiveTargets, signInAs, waitForRouteReady } from "./native-feel.helpers"
import { readSeed } from "./seed"

/*
 * B7 (Task 12) — the native-feel acceptance spec (ledger row
 * x-motion-reduced-motion-e2e-narrow-scope's e2e half; the unit half stays
 * with C4). Runs only on the `iphone-15`/`pixel-7` device projects
 * (`playwright.config.ts`'s `testMatch`), never `chromium` (`testIgnore`) —
 * every assertion below needs a real touch/mobile viewport to mean
 * anything; a desktop context would pass the size checks vacuously.
 *
 * ── Environment note (see the Task 12 commit body for the full record) ────
 * This suite needs the real backend + seeded local Supabase stack per
 * `playwright.config.ts`'s `webServer`. In the sandbox this was written in,
 * the local stack's schema was out of sync (`alembic upgrade head` failing
 * on a missing `teacher_papers` table) — pre-existing, not caused by this
 * task, and not safe to repair here since the Supabase containers are
 * shared across every worktree in this repo. Only the signed-out
 * assertions (1-4 on `/login`, and 9's `/login` half) could actually be run
 * and verified here. The signed-in halves of every assertion are written in
 * full below — never weakened or stubbed — and are deferred to CI, which
 * has its own database.
 *
 * A dismissible `<Modal>` reachable from seed data was re-grepped for under
 * `web/src/portals/student` (per this task's own instruction) and none
 * exists — every `<Modal` use there goes through `<ConfirmModal>`, which is
 * `dismissible={false}` by design. Assertion 5 therefore covers the
 * `NavDrawer` (dismissible) and a `ConfirmModal` (non-dismissible, "Delete
 * deck") case, and does not have a third dismissible-`Modal` case to add.
 */

const SIGNED_OUT_ROUTES = [
  "/login",
  "/signup",
  "/reset",
  "/join",
  "/settings/notifications",
] as const

async function loginAsStudent(page: Page): Promise<void> {
  await signInAs(page, "student")
}

async function checkFieldFontSizes(page: Page): Promise<void> {
  await waitForRouteReady(page)
  const fields = page.locator("input, textarea, select")
  const count = await fields.count()
  for (let i = 0; i < count; i++) {
    const field = fields.nth(i)
    if (!(await field.isVisible())) continue
    const fontSize = await field.evaluate((el) => Number.parseFloat(getComputedStyle(el).fontSize))
    const description = await field.evaluate(
      (el) => el.outerHTML.replace(/\n/g, " ").slice(0, 120),
    )
    expect(fontSize, description).toBeGreaterThanOrEqual(16)
  }
}

async function checkTapTargets(page: Page): Promise<void> {
  await waitForRouteReady(page)
  const targets = interactiveTargets(page)
  // Every route in this suite has at least one button/link/nav item, so an
  // empty result here means the loading-tier wait above raced something,
  // not that the route genuinely has zero controls (a vacuous pass, not a
  // real one).
  await expect(targets.first(), "expected at least one interactive control on this route").toBeVisible({
    timeout: 15_000,
  })
  const count = await targets.count()
  for (let i = 0; i < count; i++) {
    const target = targets.nth(i)
    if (!(await target.isVisible())) continue
    const box = await target.boundingBox()
    if (!box) continue
    const { name, iconOnly } = await target.evaluate((el) => ({
      name: el.getAttribute("aria-label") ?? el.textContent?.trim() ?? el.tagName,
      iconOnly: !el.textContent || el.textContent.trim().length === 0,
    }))
    expect(box.height, `${name}: tap target height`).toBeGreaterThanOrEqual(44)
    if (iconOnly) {
      expect(box.width, `${name}: icon-only tap target width`).toBeGreaterThanOrEqual(44)
    }
  }
}

test.describe("Assertion 1: form fields never trigger iOS zoom (computed font-size >= 16px)", () => {
  for (const route of SIGNED_OUT_ROUTES.slice(0, 4)) {
    test(`${route} (signed out)`, async ({ page }) => {
      await page.goto(route)
      await checkFieldFontSizes(page)
    })
  }

  test("/settings/notifications (signed in as student)", async ({ page }) => {
    await loginAsStudent(page)
    await page.goto("/settings/notifications")
    await checkFieldFontSizes(page)
  })
})

test.describe("Assertion 2: every interactive control meets the 44px tap-target minimum", () => {
  for (const route of SIGNED_OUT_ROUTES) {
    test(`${route} (signed out)`, async ({ page }) => {
      await page.goto(route)
      await checkTapTargets(page)
    })
  }

  test("/student (signed in)", async ({ page }) => {
    await loginAsStudent(page)
    await page.goto("/student")
    await checkTapTargets(page)
  })
})

test("Assertion 3: chrome-suppression computed styles", async ({ page }) => {
  await page.goto("/login")
  const tapHighlight = await page.evaluate(() =>
    getComputedStyle(document.body).getPropertyValue("-webkit-tap-highlight-color"),
  )
  expect(tapHighlight).toBe("rgba(0, 0, 0, 0)")

  const firstButton = page.getByRole("button").first()
  await expect(firstButton).toBeVisible()
  // The device projects set `hasTouch`, so `(pointer: coarse)` matches and
  // `touch-action: manipulation` (index.css:677) actually applies.
  const touchAction = await firstButton.evaluate((el) => getComputedStyle(el).touchAction)
  expect(touchAction).toBe("manipulation")

  const overscroll = await page.evaluate(
    () => getComputedStyle(document.documentElement).overscrollBehaviorY,
  )
  expect(overscroll).toBe("contain")
})

test("Assertion 4: safe-area CSS present, viewport meta exact", async ({ page }) => {
  await page.goto("/login")
  const safeAreaRuleCount = await page.evaluate(() => {
    let count = 0
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList
      try {
        rules = sheet.cssRules
      } catch {
        // Cross-origin stylesheet (e.g. Google Fonts) — not same-origin,
        // skip it per the assertion's own "same-origin stylesheets" scope.
        continue
      }
      for (const rule of Array.from(rules)) {
        if (rule.cssText.includes("safe-area-inset")) count++
      }
    }
    return count
  })
  expect(safeAreaRuleCount).toBeGreaterThan(0)

  const viewportContent = await page.locator('meta[name="viewport"]').getAttribute("content")
  expect(viewportContent).toBe(
    "width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content",
  )
})

test.describe("Assertion 5: browser back dismisses overlays without navigating away", () => {
  test("the student nav drawer (dismissible) closes on back; URL unchanged", async ({ page }) => {
    await loginAsStudent(page)
    await page.goto("/student")
    await page.getByRole("button", { name: "Open student navigation" }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    const urlBefore = page.url()

    await page.goBack()

    await expect(dialog).toBeHidden()
    expect(page.url()).toBe(urlBefore)
  })

  test("a ConfirmModal (non-dismissible, 'Delete deck') survives back; deck not deleted", async ({
    page,
  }) => {
    const seed = readSeed()
    const account = seed.practice.students.active
    await page.goto("/login")
    await page.getByLabel("Email").fill(account.email)
    await page.getByLabel("Password").fill(account.password)
    await page.getByRole("button", { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

    await page.goto(`/student/flashcards/${seed.practice.subjectCode}`)
    await expect(page.getByRole("heading", { name: /^Flashcards for/ })).toBeVisible()

    const deleteButton = page.getByRole("button", { name: /^Delete deck:/ }).first()
    await expect(deleteButton).toBeVisible()
    const deckLabel = await deleteButton.getAttribute("aria-label")

    await deleteButton.click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    const urlBefore = page.url()

    await page.goBack()

    // ConfirmModal is `dismissible={false}` — back re-pushes the history
    // entry rather than closing it (Task 2 Behaviour 2).
    await expect(dialog).toBeVisible()
    expect(page.url()).toBe(urlBefore)

    await page.getByRole("button", { name: "Keep it" }).click()
    await expect(dialog).toBeHidden()

    await page.reload()
    await expect(page.getByRole("button", { name: deckLabel ?? "" })).toBeVisible()
  })
})

test("Assertion 6: scroll restoration on POP; a fresh tab entry scrolls to top", async ({
  page,
}) => {
  await loginAsStudent(page)
  await page.goto("/student")
  await page.waitForLoadState("networkidle")
  await page.evaluate(() => window.scrollTo(0, 600))

  const nav = page.getByRole("navigation", { name: "Primary" })
  await nav.getByRole("link", { name: "Classes", exact: true }).click()
  await expect(page).toHaveURL(/\/student\/classes$/)

  await page.goBack()
  await expect(page).toHaveURL(/\/student$/)
  const restoredScrollY = await page.evaluate(() => window.scrollY)
  expect(Math.abs(restoredScrollY - 600)).toBeLessThanOrEqual(50)

  await nav.getByRole("link", { name: "Classes", exact: true }).click()
  await expect(page).toHaveURL(/\/student\/classes$/)
  const freshScrollY = await page.evaluate(() => window.scrollY)
  expect(freshScrollY).toBe(0)
})

test("Assertion 7: unauthenticated deep link redirects to login, then returns after sign-in", async ({
  page,
}) => {
  await page.goto("/student/notifications")
  await expect(page).toHaveURL(/\/login\?next=/)

  const seed = readSeed()
  await page.getByLabel("Email").fill(seed.students.control.email)
  await page.getByLabel("Password").fill(seed.students.control.password)
  await page.getByRole("button", { name: /sign in/i }).click()

  await expect(page).toHaveURL(/\/student\/notifications$/, { timeout: 15_000 })
})

test("Assertion 8: reduced motion collapses durations; overlays unmount synchronously", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await loginAsStudent(page)
  await page.goto("/student")
  await page.waitForLoadState("networkidle")

  const offenders = await page.evaluate(() => {
    function millis(cssTime: string): number {
      const value = Number.parseFloat(cssTime)
      return cssTime.trim().endsWith("ms") ? value : value * 1000
    }
    const found: string[] = []
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const style = getComputedStyle(el)
      if (style.animationName !== "none" && millis(style.animationDuration) > 10) {
        found.push(`${el.tagName}: animation-duration ${style.animationDuration}`)
      }
      for (const duration of style.transitionDuration.split(",")) {
        if (millis(duration) > 10) {
          found.push(`${el.tagName}: transition-duration ${duration.trim()}`)
          break
        }
      }
    }
    return found
  })
  expect(offenders).toEqual([])

  await page.getByRole("button", { name: "Open student navigation" }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.getByRole("button", { name: "Close navigation" }).click()
  // Reduced motion unmounts overlays synchronously (Task 3 Behaviour 5) —
  // one rAF is enough to observe the DOM having already settled.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)))
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test.describe("Assertion 9: zero request failures / 4xx+ responses on a cold load", () => {
  test("/login", async ({ page }) => {
    const events = failedRequests(page)
    await page.goto("/login")
    await page.waitForLoadState("networkidle")
    expect(events).toEqual([])
  })

  test("/student (signed in)", async ({ page }) => {
    const events = failedRequests(page)
    await loginAsStudent(page)
    await page.waitForLoadState("networkidle")
    expect(events).toEqual([])
  })
})

// Assertion 10 (optional, not gating per the plan — a network-timing race by
// nature, so a flake here should not block landing this packet; every other
// assertion above is the real bar).
test("Assertion 10 (optional): CorrectPaper shows its skeleton before content on a throttled chunk load", async ({
  page,
}) => {
  await loginAsStudent(page)
  await page.route("**/*CorrectPaper*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800))
    await route.continue()
  })
  const gotoPromise = page.goto("/student/correct")
  await expect(page.locator('[data-tier="skeleton"]')).toBeVisible({ timeout: 5_000 })
  await gotoPromise
})
