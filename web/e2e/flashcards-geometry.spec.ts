import { expect, test, type BrowserContext, type Page } from "@playwright/test"

/*
 * Rendered geometry of the flashcards review screens against the bottom tabs. DB-free: every
 * request is a synthetic page.route fixture, so this runs with flashcards-geometry.config.ts and
 * none of the acceptance suite's global setup. The regression it guards: the shell's banners
 * (iOS install, offline, verify email) sit above the screen inside <main>, so a viewport-height
 * calculation that only subtracts bars pushed "Show answer" under the tabs on first paint.
 */

// Set GEOMETRY_ARTIFACTS to keep the screenshots somewhere durable; otherwise they go to the test output folder.
const artifacts = process.env.GEOMETRY_ARTIFACTS
const b64 = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url")
const session = { accessToken: `${b64({ alg: "none" })}.${b64({ exp: 4102444800 })}.x`, refreshToken: null, userId: "u1", role: "student" }
const makeCard = (front: string) => ({ id: "card-1", front, back: "A quantity with magnitude and direction", position: 0, source: "manual", sourceQuestionId: null, repetitions: 0, easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2025-01-01T00:00:00Z", lastReviewedAt: null, nextIntervalDays: { again: 0, hard: 1, good: 2, easy: 4 } })
const ios = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
const android = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

interface Options { front?: string; unverified?: boolean }

async function open(context: BrowserContext, options: Options = {}): Promise<Page> {
  const page = await context.newPage()
  const card = makeCard(options.front ?? "What is a vector?")
  await page.addInitScript((value) => localStorage.setItem("lemely.session", JSON.stringify(value)), session)
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith("/flashcards/due")) return route.fulfill({ json: { cards: [card], totalDue: 1, nextDueAt: null, upcoming: [], againDelayMinutes: 10 } })
    if (path.endsWith("/cards/card-1/review")) return route.fulfill({ json: { card, reviewId: "review-1", grade: "good", intervalBeforeDays: 0, intervalAfterDays: 2, xpAwarded: 10 } })
    if (path.endsWith("/flashcards/decks/deck-1")) return route.fulfill({ json: { id: "deck-1", subjectCode: "9709", title: "Vectors", origin: "manual", cards: [card], dueCount: 1 } })
    if (path.endsWith("/me/student-profile")) return route.fulfill({ json: { profile: { qualificationLevel: null, onboardingCompletedAt: "2025-01-01T00:00:00Z" }, enrolments: [] } })
    if (path.endsWith("/me/profile")) return route.fulfill({ json: { email: "student@example.com", displayName: "Student", emailVerified: !options.unverified } })
    if (path.endsWith("/reference")) return route.fulfill({ json: { subjects: [], qualificationLevels: [] } })
    if (path.endsWith("/access/config")) return route.fulfill({ json: { restricted: false } })
    return route.fulfill({ json: {} })
  })
  await page.goto("/student/flashcards/review?deck=deck-1")
  await expect(page.getByRole("button", { name: /^Show answer/ })).toBeVisible()
  return page
}

/** Bottom edge of `target` against the top of the bottom tabs (or the viewport where there are none). */
async function measure(page: Page, name: string, target: ReturnType<Page["getByRole"]>, hasNav: boolean) {
  const box = await target.boundingBox()
  expect(box).not.toBeNull()
  const navBox = hasNav ? await page.getByRole("navigation", { name: "Primary" }).boundingBox() : null
  const measurement = { name, bottom: box!.y + box!.height, navTop: navBox?.y ?? null, scrollY: await page.evaluate(() => window.scrollY), viewport: page.viewportSize() }
  console.log("MEASUREMENT", JSON.stringify(measurement))
  await page.screenshot({ path: artifacts ? `${artifacts}/${name}.png` : test.info().outputPath(`${name}.png`) })
  if (hasNav) {
    expect(navBox).not.toBeNull()
    expect(measurement.bottom).toBeLessThanOrEqual(navBox!.y)
  } else {
    expect(measurement.bottom).toBeLessThanOrEqual(page.viewportSize()!.height)
  }
}

const showAnswer = (page: Page) => page.getByRole("button", { name: /^Show answer/ })

for (const item of [
  { name: "ios-380", width: 380, ua: ios, mobile: true, banner: true, nav: true },
  { name: "ios-768", width: 768, ua: ios, mobile: true, banner: true, nav: true },
  { name: "ios-1440", width: 1440, ua: ios, mobile: true, banner: true, nav: false },
  { name: "web-380", width: 380, ua: undefined, mobile: false, banner: false, nav: true },
  { name: "web-768", width: 768, ua: undefined, mobile: false, banner: false, nav: true },
  { name: "web-1440", width: 1440, ua: undefined, mobile: false, banner: false, nav: false },
  { name: "android-380", width: 380, ua: android, mobile: true, banner: false, nav: true },
]) {
  test(`${item.name} clears navigation`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: item.width, height: 844 }, userAgent: item.ua, isMobile: item.mobile, hasTouch: item.mobile, reducedMotion: "reduce" })
    const page = await open(context)
    const dismiss = page.getByRole("button", { name: "Dismiss install banner" })
    if (item.banner) await expect(dismiss).toBeVisible()
    else await expect(dismiss).toHaveCount(0)
    await measure(page, `${item.name}-shown`, showAnswer(page), item.nav)
    if (item.banner) {
      await dismiss.click()
      await expect(dismiss).toHaveCount(0)
      await measure(page, `${item.name}-dismissed`, showAnswer(page), item.nav)
    }
    await context.close()
  })
}

test("ios-380 revealed grade buttons clear the tabs under the install banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
  await showAnswer(page).click()
  await expect(page.getByRole("group", { name: "How well did you know it?" })).toBeVisible()
  await measure(page, "ios-380-revealed", page.getByRole("group", { name: "How well did you know it?" }), true)
  await context.close()
})

test("ios-380 done screen clears the tabs under the install banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
  await showAnswer(page).click()
  await page.getByRole("group", { name: "How well did you know it?" }).getByRole("button").nth(2).click()
  const back = page.getByRole("button", { name: "Back to decks" })
  await expect(back).toBeVisible()
  await measure(page, "ios-380-done", back, true)
  await context.close()
})

test("ios-380 clears navigation with the offline, verify-email and install banners all stacked", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context, { unverified: true })
  await expect(page.getByText("Your email isn't verified yet.")).toBeVisible()
  await context.setOffline(true)
  await expect(page.getByText("You're offline.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
  // Three banners plus the card's 320px minimum no longer fit: the page must scroll, and the end of it must clear the tabs.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
  await measure(page, "ios-380-all-banners", showAnswer(page), true)
  await context.close()
})

test("android-380 clears navigation under the offline banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: android, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  await context.setOffline(true)
  await expect(page.getByText("You're offline.")).toBeVisible()
  await measure(page, "android-380-offline", showAnswer(page), true)
  await context.close()
})

test("web-380 clears navigation under the verify-email banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, reducedMotion: "reduce" })
  const page = await open(context, { unverified: true })
  await expect(page.getByText("Your email isn't verified yet.")).toBeVisible()
  await measure(page, "web-380-verify", showAnswer(page), true)
  await context.close()
})

test("short viewport keeps ordinary document scrolling", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 480 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(480)
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
  await measure(page, "ios-short-scrolled", showAnswer(page), true)
  await context.close()
})

test("long card content stays inside the card and above the tabs", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const front = Array.from({ length: 60 }, (_, i) => `Line ${i + 1} of a very long question about vectors.`).join(" ")
  const page = await open(context, { front })
  await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
  await measure(page, "ios-380-long-content", showAnswer(page), true)
  await context.close()
})
