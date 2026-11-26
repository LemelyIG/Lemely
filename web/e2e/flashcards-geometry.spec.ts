import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test"

/*
 * Rendered geometry of the flashcards review screens against the bottom tabs. DB-free: every
 * request is a synthetic page.route fixture, so this runs with flashcards-geometry.config.ts and
 * none of the acceptance suite's global setup. The regression it guards: the shell's banners
 * (iOS install, offline, verify email) sit above the screen inside <main>, so a viewport-height
 * calculation that only subtracts bars pushed "Show answer" under the tabs on first paint.
 *
 * Two kinds of case, kept apart: "fits" cases promise the action is on screen at first paint, so the page
 * must not scroll (and bringing the action into view must not scroll it either); "scrolls" cases are the
 * intentional ones (stacked banners, a 480px-tall viewport) where the document scrolls and only its end is checked.
 * Card-content cases additionally prove the question and hint stay inside the card, the card ends above the
 * action and the action ends above the tabs, however long the question is.
 */

// Set GEOMETRY_ARTIFACTS to keep the screenshots somewhere durable; otherwise they go to the test output folder.
const artifacts = process.env.GEOMETRY_ARTIFACTS
const b64 = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url")
const session = { accessToken: `${b64({ alg: "none" })}.${b64({ exp: 4102444800 })}.x`, refreshToken: null, userId: "u1", role: "student" }
const makeCard = (front: string, source: "manual" | "ai") => ({ id: "card-1", front, back: "A quantity with magnitude and direction", position: 0, source, sourceQuestionId: null, repetitions: 0, easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2025-01-01T00:00:00Z", lastReviewedAt: null, nextIntervalDays: { again: 0, hard: 1, good: 2, easy: 4 } })
const ios = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
const android = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

interface Options { front?: string; unverified?: boolean; source?: "manual" | "ai" }

async function open(context: BrowserContext, options: Options = {}): Promise<Page> {
  const page = await context.newPage()
  const card = makeCard(options.front ?? "What is a vector?", options.source ?? "manual")
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

type Mode = "fits" | "scrolls"

/** A "fits" case: the page starts unscrolled and scrolling the action into view moves nothing, so the action is on screen at first paint. */
async function expectNoPageScroll(target: ReturnType<Page["getByRole"]>) {
  const probe = await target.evaluate((el) => {
    const before = window.scrollY
    el.scrollIntoView({ block: "nearest", inline: "nearest" })
    const after = window.scrollY
    window.scrollTo(0, 0)
    return { before, after }
  })
  expect(probe.before, "the page starts unscrolled").toBe(0)
  expect(probe.after, "bringing the action into view must not scroll the page").toBe(0)
}

const capture = (page: Page, name: string) => page.screenshot({ path: artifacts ? `${artifacts}/${name}.png` : test.info().outputPath(`${name}.png`) })

/** Bottom edge of `target` against the top of the bottom tabs (or the viewport where there are none). */
async function measure(page: Page, name: string, target: ReturnType<Page["getByRole"]>, hasNav: boolean, mode: Mode) {
  if (mode === "fits") await expectNoPageScroll(target)
  const box = await target.boundingBox()
  expect(box).not.toBeNull()
  const navBox = hasNav ? await page.getByRole("navigation", { name: "Primary" }).boundingBox() : null
  const measurement = { name, mode, bottom: box!.y + box!.height, navTop: navBox?.y ?? null, scrollY: await page.evaluate(() => window.scrollY), viewport: page.viewportSize() }
  console.log("MEASUREMENT", JSON.stringify(measurement))
  await page.screenshot({ path: artifacts ? `${artifacts}/${name}.png` : test.info().outputPath(`${name}.png`) })
  if (mode === "fits") expect(measurement.scrollY, "a fits case never scrolls").toBe(0)
  if (hasNav) {
    expect(navBox).not.toBeNull()
    expect(measurement.bottom).toBeLessThanOrEqual(navBox!.y)
  } else {
    expect(measurement.bottom).toBeLessThanOrEqual(page.viewportSize()!.height)
  }
}

const BACK = "A quantity with magnitude and direction"
const HINT = "Tap to flip"
const LONG_244 = "A particle starts from rest and moves in a straight line with constant acceleration, covering 36 metres in the first 4 seconds. Find the acceleration, the speed after 6 seconds, and the distance travelled in that time. Show all of your working."
const ARABIC_LONG = "يبدأ جسيم من السكون ويتحرك في خط مستقيم بتسارع ثابت فيقطع ستة وثلاثين مترا في أول أربع ثوان. أوجد التسارع والسرعة بعد ست ثوان والمسافة التي يقطعها الجسيم في ذلك الزمن. اكتب جميع خطوات الحل بالتفصيل مع ذكر القوانين المستخدمة في كل خطوة."

interface Rect { top: number; bottom: number; left: number; right: number }
interface CardReport {
  /** The visible card (the face's frame). */
  card: Rect
  /** What the reader sees of the text: the scrolling element's box, or the card when nothing scrolls. */
  port: Rect
  action: Rect; nav: Rect | null; viewportHeight: number
  atStart: { question: Rect; last: Rect }; atEnd: { question: Rect; last: Rect }
  scrolls: boolean; coveredAtEnd: boolean; centerDelta: number
  /** The AI mark's box and the tallest overlap (px) any painted text line has with it at any scroll position; null when the card has no mark. */
  mark: Rect | null; markOverlap: number
}

/** The element a card's text scrolls in: the face itself, or a body inside it (the earlier structure). Runs in the page. */
const findScroller = (face: Element) =>
  [face, ...Array.from(face.querySelectorAll("*"))].find((node) => /(auto|scroll)/.test(getComputedStyle(node).overflowY)) as HTMLElement

/**
 * Where everything sits on a card screen. The scrolling body (if the face has one) is driven to its start and
 * to its end so the question's first line and the last line (the hint, or the answer once flipped) are both
 * measured where a reader would see them; the body is put back at its start before returning.
 */
async function inspectCard(page: Page, front: string, action: ReturnType<Page["getByRole"]>, revealed: boolean, hasNav: boolean): Promise<CardReport> {
  const handle = await action.elementHandle()
  expect(handle).not.toBeNull()
  const navHandle = hasNav ? await page.getByRole("navigation", { name: "Primary" }).elementHandle() : null
  return page.evaluate(({ front, lastText, action, nav }) => {
    const rect = (el: Element): Rect => { const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right } }
    const face = document.querySelector('[role="button"][data-review-primary]')!
    const frame = face.parentElement!
    const spans = [...face.querySelectorAll("span")]
    const question = spans.find((s) => s.textContent === front)!
    const last = spans.find((s) => s.textContent === lastText)!
    const scroller = [face, ...Array.from(face.querySelectorAll("*"))].find((node) => /(auto|scroll)/.test(getComputedStyle(node).overflowY)) as HTMLElement | undefined ?? null
    const scrolls = scroller !== null && scroller.scrollHeight > scroller.clientHeight + 1
    if (scroller) scroller.scrollTop = 0
    const port = rect(scroller ?? frame)
    const atStart = { question: rect(question), last: rect(last) }
    const centerDelta = Math.abs((atStart.question.top + atStart.last.bottom) / 2 - (rect(frame).top + rect(frame).bottom) / 2)
    if (scroller) scroller.scrollTop = scroller.scrollHeight
    const atEnd = { question: rect(question), last: rect(last) }
    const hit = document.elementFromPoint((atEnd.last.left + atEnd.last.right) / 2, (atEnd.last.top + atEnd.last.bottom) / 2)
    const coveredAtEnd = !(hit !== null && last.contains(hit))
    // The AI mark is a glyph plus "AI" and no background: no line of text may ever be painted under it, at any scroll position.
    const markEl = [...frame.querySelectorAll("span")].find((s) => s.querySelector("svg") !== null && (s.textContent ?? "").includes("AI")) ?? null
    const mark = markEl ? rect(markEl) : null
    let markOverlap = 0
    if (mark && scroller) {
      const reach = scroller.scrollHeight - scroller.clientHeight
      for (let offset = 0; offset <= reach + 24; offset += 24) {
        scroller.scrollTop = Math.min(offset, reach)
        for (const span of [question, last]) {
          const range = document.createRange()
          range.selectNodeContents(span)
          for (const line of Array.from(range.getClientRects())) {
            // Only what the scroller paints counts: a line scrolled out of the port is not drawn.
            const vertical = Math.min(line.bottom, port.bottom, mark.bottom) - Math.max(line.top, port.top, mark.top)
            const horizontal = Math.min(line.right, mark.right) - Math.max(line.left, mark.left)
            if (vertical > 1 && horizontal > 1) markOverlap = Math.max(markOverlap, vertical)
          }
        }
      }
    }
    if (scroller) scroller.scrollTop = 0
    return { card: rect(frame), port, action: rect(action), nav: nav ? rect(nav) : null, viewportHeight: window.innerHeight, atStart, atEnd, scrolls, coveredAtEnd, centerDelta, mark, markOverlap }
  }, { front, lastText: revealed ? BACK : HINT, action: handle!, nav: navHandle })
}

/** The brief's geometry: question and hint inside the card, card above the action, action above the tabs. */
async function expectCardReadable(page: Page, front: string, action: ReturnType<Page["getByRole"]>, opts: { revealed?: boolean; hasNav: boolean; expectScroll?: boolean }) {
  const r = await inspectCard(page, front, action, opts.revealed ?? false, opts.hasNav)
  console.log("CARD", JSON.stringify({ front: front.length, card: r.card, action: r.action, scrolls: r.scrolls, centerDelta: r.centerDelta }))
  if (opts.expectScroll !== undefined) expect(r.scrolls, "the face scrolls its own content").toBe(opts.expectScroll)
  for (const [label, at] of [["start", r.atStart], ["end", r.atEnd]] as const) {
    expect(at.question.left, `question inside the card at the ${label}`).toBeGreaterThanOrEqual(r.card.left)
    expect(at.question.right, `question inside the card at the ${label}`).toBeLessThanOrEqual(r.card.right)
    expect(at.last.left, `last line inside the card at the ${label}`).toBeGreaterThanOrEqual(r.card.left)
    expect(at.last.right, `last line inside the card at the ${label}`).toBeLessThanOrEqual(r.card.right)
  }
  expect(r.atStart.question.top, "the top of the question is readable at the start").toBeGreaterThanOrEqual(r.port.top)
  expect(r.atEnd.last.bottom, "the hint (or answer) is readable at the end").toBeLessThanOrEqual(r.port.bottom)
  if (r.mark) expect(r.markOverlap, "no line of text is ever painted under the AI mark").toBe(0)
  expect(r.coveredAtEnd, "nothing covers the last line").toBe(false)
  expect(r.card.bottom, "the card ends above the action").toBeLessThanOrEqual(r.action.top)
  expect(r.action.bottom, "the action ends above the tabs").toBeLessThanOrEqual(r.nav ? r.nav.top : r.viewportHeight)
  return r
}

/** 44px targets: every button in the action area (the lone Show answer, or the four grades). */
async function expectTargets(buttons: ReturnType<Page["getByRole"]>) {
  const count = await buttons.count()
  expect(count).toBeGreaterThan(0)
  for (let i = 0; i < count; i++) {
    const box = await buttons.nth(i).boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
    expect(box!.width).toBeGreaterThanOrEqual(44)
  }
}

interface Env { width: number; height?: number; ua?: string; mobile: boolean; colorScheme?: "dark" | "light" }
const newContext = (browser: Browser, env: Env) => browser.newContext({
  viewport: { width: env.width, height: env.height ?? 844 }, userAgent: env.ua, isMobile: env.mobile, hasTouch: env.mobile, reducedMotion: "reduce", colorScheme: env.colorScheme,
})
const IOS_380: Env = { width: 380, ua: ios, mobile: true }

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
    await measure(page, `${item.name}-shown`, showAnswer(page), item.nav, "fits")
    if (item.banner) {
      await dismiss.click()
      await expect(dismiss).toHaveCount(0)
      await measure(page, `${item.name}-dismissed`, showAnswer(page), item.nav, "fits")
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
  await measure(page, "ios-380-revealed", page.getByRole("group", { name: "How well did you know it?" }), true, "fits")
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
  await measure(page, "ios-380-done", back, true, "fits")
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
  await measure(page, "ios-380-all-banners", showAnswer(page), true, "scrolls")
  await context.close()
})

test("android-380 clears navigation under the offline banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, userAgent: android, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  await context.setOffline(true)
  await expect(page.getByText("You're offline.")).toBeVisible()
  await measure(page, "android-380-offline", showAnswer(page), true, "fits")
  await context.close()
})

test("web-380 clears navigation under the verify-email banner", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 844 }, reducedMotion: "reduce" })
  const page = await open(context, { unverified: true })
  await expect(page.getByText("Your email isn't verified yet.")).toBeVisible()
  await measure(page, "web-380-verify", showAnswer(page), true, "fits")
  await context.close()
})

test("short viewport keeps ordinary document scrolling", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 380, height: 480 }, userAgent: ios, isMobile: true, hasTouch: true, reducedMotion: "reduce" })
  const page = await open(context)
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(480)
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
  await measure(page, "ios-short-scrolled", showAnswer(page), true, "scrolls")
  await context.close()
})

test.describe("card content stays inside the card, above the action, above the tabs", () => {
  test("ios-380 244-character question under the install banner scrolls inside the card, never into Show answer", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const page = await open(context, { front: LONG_244 })
    await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
    await expectCardReadable(page, LONG_244, showAnswer(page), { hasNav: true })
    await expectTargets(showAnswer(page))
    await measure(page, "ios-380-long-244", showAnswer(page), true, "fits")
    await context.close()
  })

  test("an extreme 60-line question must scroll inside the face and still clear the action and tabs", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const front = Array.from({ length: 60 }, (_, i) => `Line ${i + 1} of a very long question about vectors.`).join(" ")
    const page = await open(context, { front })
    await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
    await expectCardReadable(page, front, showAnswer(page), { hasNav: true, expectScroll: true })
    await measure(page, "ios-380-long-content", showAnswer(page), true, "fits")
    await context.close()
  })

  for (const env of [
    { name: "ios-380", ...IOS_380 },
    { name: "web-768", width: 768, mobile: false },
    { name: "web-1440", width: 1440, mobile: false },
  ]) {
    for (const [label, front] of [["short", "What is a vector?"], ["word", "Vector"]] as const) {
      test(`${env.name} ${label} card stays centred, unscrolled and above the action`, async ({ browser }) => {
        const context = await newContext(browser, env)
        const page = await open(context, { front })
        const hasNav = env.width < 1024
        const r = await expectCardReadable(page, front, showAnswer(page), { hasNav, expectScroll: false })
        expect(r.centerDelta, "a short card keeps its text centred in the face").toBeLessThanOrEqual(2)
        await expectTargets(showAnswer(page))
        await measure(page, label === "short" ? `${env.name}-short` : `${env.name}-short-word`, showAnswer(page), hasNav, "fits")
        await context.close()
      })
    }
  }

  test("ios-380 flipped 244-character card keeps question and answer inside the face above the grades", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const page = await open(context, { front: LONG_244 })
    await showAnswer(page).click()
    const grades = page.getByRole("group", { name: "How well did you know it?" })
    await expect(grades).toBeVisible()
    await expectCardReadable(page, LONG_244, grades, { revealed: true, hasNav: true })
    await expectTargets(grades.getByRole("button"))
    await measure(page, "ios-380-long-244-revealed", grades, true, "fits")
    await context.close()
  })

  test("ios-380 244-character question in dark mode is readable and really dark", async ({ browser }) => {
    const light = await newContext(browser, IOS_380)
    const lightPage = await open(light, { front: LONG_244 })
    // The surface colour lives on the face's frame, the visible card.
    const lightBg = await lightPage.locator('[role="button"][data-review-primary]').evaluate((el) => getComputedStyle(el.parentElement!).backgroundColor)
    await light.close()
    const context = await newContext(browser, { ...IOS_380, colorScheme: "dark" })
    const page = await open(context, { front: LONG_244 })
    expect(await page.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches)).toBe(true)
    const darkBg = await page.locator('[role="button"][data-review-primary]').evaluate((el) => getComputedStyle(el.parentElement!).backgroundColor)
    expect(darkBg, "the card surface changes with the theme").not.toBe(lightBg)
    await expectCardReadable(page, LONG_244, showAnswer(page), { hasNav: true })
    await measure(page, "ios-380-long-244-dark", showAnswer(page), true, "fits")
    await context.close()
  })

  test("ios-380 244-character Arabic question in RTL is readable and stays inside the card", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const page = await open(context, { front: ARABIC_LONG })
    await page.evaluate(() => { document.documentElement.dir = "rtl"; document.documentElement.lang = "ar" })
    await expectCardReadable(page, ARABIC_LONG, showAnswer(page), { hasNav: true })
    await expectTargets(showAnswer(page))
    await measure(page, "ios-380-long-244-rtl", showAnswer(page), true, "fits")
    await context.close()
  })

  test("a long card scrolls from the keyboard and the wheel without moving the page", async ({ browser }) => {
    const context = await newContext(browser, { width: 380, mobile: false })
    const front = Array.from({ length: 12 }, (_, i) => `Line ${i + 1} of a long question about vectors and their uses.`).join(" ")
    const page = await open(context, { front })
    const card = page.locator('[role="button"][data-review-primary]')
    const body = await card.evaluateHandle(findScroller)
    const top = () => body.evaluate((el) => el.scrollTop)
    expect(await body.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    await card.focus()
    await page.keyboard.press("PageDown")
    await expect.poll(top).toBeGreaterThan(0)
    const afterPage = await top()
    await page.keyboard.press("ArrowDown")
    await expect.poll(top, "an arrow key scrolls a few lines").toBeGreaterThan(afterPage)
    await page.keyboard.press("ArrowUp")
    await expect.poll(top).toBe(afterPage)
    await page.keyboard.press("PageUp")
    await expect.poll(top).toBe(0)
    await expect(card, "scrolling from the keyboard keeps focus on the card").toBeFocused()
    await expect(page.getByRole("group", { name: "How well did you know it?" })).toHaveCount(0)
    const box = (await card.boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 240)
    await expect.poll(top).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
    await context.close()
  })

  test("a right swipe over the scrolling body still flips the card", async ({ browser }) => {
    const context = await newContext(browser, { width: 380, mobile: false })
    const page = await open(context, { front: LONG_244 })
    const box = (await page.locator('[role="button"][data-review-primary]').boundingBox())!
    const y = box.y + box.height / 2
    await page.mouse.move(box.x + 60, y)
    await page.mouse.down()
    await page.mouse.move(box.x + 300, y, { steps: 12 })
    await page.mouse.up()
    await expect(page.getByRole("group", { name: "How well did you know it?" })).toBeVisible()
    await context.close()
  })
  // The same long card with the AI mark: the scrolling face must end above the mark, so no line is ever painted under it.
  test("ios-380 244-character AI card scrolls clear of the AI mark, before and after the flip", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const page = await open(context, { front: LONG_244, source: "ai" })
    await expect(page.getByRole("button", { name: "Dismiss install banner" })).toBeVisible()
    const before = await expectCardReadable(page, LONG_244, showAnswer(page), { hasNav: true, expectScroll: true })
    expect(before.mark, "the AI mark is on the card").not.toBeNull()
    expect(before.mark!.bottom, "the mark sits inside the card").toBeLessThanOrEqual(before.card.bottom)
    await expectTargets(showAnswer(page))
    await measure(page, "ios-380-long-244-ai", showAnswer(page), true, "fits")
    // Mid-scroll capture: text passes under where the mark would be if the face did not end above it.
    const body = await page.locator('[role="button"][data-review-primary]').evaluateHandle(findScroller)
    await body.evaluate((el) => { el.scrollTop = (el.scrollHeight - el.clientHeight) / 2 })
    await capture(page, "ios-380-long-244-ai-mid-scroll")
    await body.evaluate((el) => { el.scrollTop = 0 })
    await showAnswer(page).click()
    const grades = page.getByRole("group", { name: "How well did you know it?" })
    await expect(grades).toBeVisible()
    const after = await expectCardReadable(page, LONG_244, grades, { revealed: true, hasNav: true })
    expect(after.mark).not.toBeNull()
    await measure(page, "ios-380-long-244-ai-revealed", grades, true, "fits")
    await context.close()
  })

  test("a short AI card keeps its text centred and unscrolled, with the mark in the corner", async ({ browser }) => {
    const context = await newContext(browser, IOS_380)
    const page = await open(context, { front: "What is a vector?", source: "ai" })
    const r = await expectCardReadable(page, "What is a vector?", showAnswer(page), { hasNav: true, expectScroll: false })
    expect(r.centerDelta, "an AI card is centred in the card exactly as a manual one is").toBeLessThanOrEqual(2)
    expect(r.mark, "the AI mark is on the card").not.toBeNull()
    expect(r.card.bottom - r.mark!.bottom, "the mark sits in the bottom corner").toBeLessThan(24)
    await measure(page, "ios-380-short-ai", showAnswer(page), true, "fits")
    await context.close()
  })

  // One tab stop per card. Chromium makes a scroll container keyboard-focusable, so an inner scroller inside the card's
  // role="button" would be a second, unnamed stop (axe: scrollable-region-focusable); the face itself must be the scroller.
  for (const source of ["manual", "ai"] as const) {
    test(`a long ${source} card is one named tab stop with a ring around the whole card, and axe finds nothing serious`, async ({ browser }) => {
      const context = await newContext(browser, IOS_380)
      const page = await open(context, { front: LONG_244, source })
      const face = page.locator('[role="button"][data-review-primary]')
      const active = () => page.evaluate(() => {
        const el = document.activeElement
        return el ? { tag: el.tagName.toLowerCase(), role: el.getAttribute("role"), label: el.getAttribute("aria-label"), primary: el.hasAttribute("data-review-primary") } : null
      })
      // Reach the card with the keyboard from the top of the page, so :focus-visible is real.
      for (let i = 0; i < 25 && !(await face.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab")
      await expect(face).toBeFocused()
      const body = await face.evaluateHandle(findScroller)
      const overflow = await body.evaluate((el) => el.scrollHeight - el.clientHeight)
      expect(overflow, "the card overflows, so this proves the scroll case").toBeGreaterThan(1)

      await capture(page, `ios-380-long-244-${source}-focus-ring`)
      // The ring goes around the whole card (frame), in the focus-ring colour, and the scroller adds no second, shorter ring.
      const ring = await face.evaluate((el) => {
        const frame = el.parentElement!
        const visible = (node: Element) => {
          const cs = getComputedStyle(node)
          const alpha = /rgba?\([^)]*,\s*([\d.]+)\)/.exec(cs.outlineColor)?.[1]
          return cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2 && (alpha === undefined || parseFloat(alpha) > 0)
        }
        const rings = [el, frame].filter(visible)
        const box = (node: Element) => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right } }
        return { count: rings.length, ringBox: rings[0] ? box(rings[0]) : null, card: box(frame) }
      })
      expect(ring.count, "exactly one visible focus ring").toBe(1)
      expect(Math.abs(ring.ringBox!.top - ring.card.top), "ring top meets the card").toBeLessThanOrEqual(1)
      expect(Math.abs(ring.ringBox!.bottom - ring.card.bottom), "ring bottom meets the card").toBeLessThanOrEqual(1)
      expect(Math.abs(ring.ringBox!.left - ring.card.left)).toBeLessThanOrEqual(1)
      expect(Math.abs(ring.ringBox!.right - ring.card.right)).toBeLessThanOrEqual(1)

      // Tab leaves the card for Show answer, not for a scroll body; Shift+Tab comes straight back to the card.
      await page.keyboard.press("Tab")
      expect(await active(), "Tab goes from the card to Show answer").toMatchObject({ tag: "button", primary: true })
      expect((await active())!.label).toMatch(/^Show answer/)
      await page.keyboard.press("Shift+Tab")
      await expect(face, "Shift+Tab returns to the card, with no stop in between").toBeFocused()

      await context.close()
    })
  }

  for (const source of ["manual", "ai"] as const) {
    test(`a long ${source} card, front and flipped, has no serious or critical axe violation`, async ({ browser }) => {
      const context = await newContext(browser, IOS_380)
      const page = await open(context, { front: LONG_244, source })
      const face = page.locator('[role="button"][data-review-primary]')
      await face.focus()
      for (const revealed of [false, true]) {
        if (revealed) {
          await page.keyboard.press("Space")
          await expect(page.getByRole("group", { name: "How well did you know it?" })).toBeVisible()
        }
        const results = await new AxeBuilder({ page })
          .include('[role="button"][data-review-primary]')
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze()
        const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
        expect(
          blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
          `axe serious or critical violations on the ${revealed ? "flipped" : "front"} ${source} card`,
        ).toEqual([])
      }
      await context.close()
    })
  }

  // Flipping resets the scroll: the answer side always opens at its top, however far the front was read.
  for (const route of ["keyboard", "Show answer"] as const) {
    test(`flipping a card scrolled to its end by ${route} opens the answer side at its top`, async ({ browser }) => {
      const context = await newContext(browser, IOS_380)
      const front = Array.from({ length: 60 }, (_, i) => `Line ${i + 1} of a very long question about vectors.`).join(" ")
      const page = await open(context, { front })
      const face = page.locator('[role="button"][data-review-primary]')
      const body = await face.evaluateHandle(findScroller)
      await body.evaluate((el) => { el.scrollTop = el.scrollHeight })
      expect(await body.evaluate((el) => el.scrollTop), "the front is scrolled to its end").toBeGreaterThan(1000)
      if (route === "keyboard") {
        await face.focus()
        await page.keyboard.press("Space")
      } else {
        await showAnswer(page).click()
      }
      const grades = page.getByRole("group", { name: "How well did you know it?" })
      await expect(grades).toBeVisible()
      await expect.poll(() => body.evaluate((el) => el.scrollTop), "the answer side opens at its top").toBe(0)
      const first = await page.evaluate(() => {
        const card = document.querySelector('[role="button"][data-review-primary]')!
        const question = [...card.querySelectorAll("span")][0]
        const r = question.getBoundingClientRect()
        const port = ([card, ...Array.from(card.querySelectorAll("*"))].find((n) => /(auto|scroll)/.test(getComputedStyle(n).overflowY)) ?? card).getBoundingClientRect()
        return { top: r.top, portTop: port.top }
      })
      expect(first.top, "the first line of the question is in view").toBeGreaterThanOrEqual(first.portTop)
      await context.close()
    })
  }
})
