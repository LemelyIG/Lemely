import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/*
 * The one theme rule: effective theme = signed in ? the user's preference : light.
 * Anonymous visitors never see dark (any route, state screen or portalled popup), whatever the OS
 * says; a signed-in user keeps their choice; signing out flips to light with no reload.
 * Fully mocked; needs the vite server only.
 */
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const session = {
  accessToken: `${b64({ alg: 'none' })}.${b64({ exp: 4102444800 })}.x`,
  refreshToken: null,
  userId: 'u1',
  role: 'student',
}

async function mock(page: Page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/access/config')) return route.fulfill({ json: { restricted: true } })
    if (url.includes('/api/waitlist/config'))
      return route.fulfill({ json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'x' } })
    return route.fulfill({ status: 404, json: { detail: 'not found' } })
  })
}
const theme = (page: Page) => page.evaluate(() => document.documentElement.dataset.theme)
/** Lightness 0..1 of a computed colour, whether the browser reports it as `oklch(L ...)` or `rgb(...)`. */
const lightnessOf = (css: string) => {
  if (css.startsWith('oklch')) return parseFloat(css.slice(6))
  const [r, g, b] = (css.match(/[\d.]+/g) ?? ['0', '0', '0']).map(Number)
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}
const surfaceIsLight = async (page: Page) =>
  lightnessOf(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)) > 0.5

test.describe('anonymous visitor on a dark OS', () => {
  test.use({ colorScheme: 'dark' })
  for (const path of ['/landing', '/login', '/signup', '/coming-soon', '/session-ended', '/no-such-page']) {
    test(`${path} stays light`, async ({ page }) => {
      await mock(page)
      await page.goto(path)
      await page.waitForTimeout(600)
      expect(await theme(page)).toBe('light')
      expect(await surfaceIsLight(page)).toBe(true)
    })
  }

  test('the waitlist dialog (portalled) is light', async ({ page }) => {
    await mock(page)
    await page.goto('/landing')
    await page.locator('.brand-hero .brand-actions button').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    const lightness = lightnessOf(await dialog.evaluate((e) => getComputedStyle(e).backgroundColor))
    expect(lightness).toBeGreaterThan(0.5)
  })
})

test.describe('signed-in user with a dark preference', () => {
  test.beforeEach(async ({ page }) => {
    await mock(page)
    await page.addInitScript((s) => {
      localStorage.setItem('lemely.session', JSON.stringify(s))
      localStorage.setItem('lemely.theme', 'dark')
    }, session)
  })

  test('the landing is dark, and signing out flips it to light without a reload', async ({ page }) => {
    await page.goto('/landing')
    await page.waitForTimeout(600)
    expect(await theme(page)).toBe('dark')
    await expect.poll(() => surfaceIsLight(page)).toBe(false)
    await page.evaluate(() => { (window as unknown as { __kept: number }).__kept = 1 })
    await page.evaluate(async () => {
      // The dev server serves the app's own module, so this is the same instance the app uses.
      const modulePath = '/src/lib/auth/storage.ts'
      const storage = await import(/* @vite-ignore */ modulePath)
      await storage.endSession()
    })
    await expect.poll(() => theme(page)).toBe('light')
    expect(await page.evaluate(() => (window as unknown as { __kept?: number }).__kept)).toBe(1)
    await expect.poll(() => surfaceIsLight(page)).toBe(true)
  })
})

/*
 * State screens in the real app. The lazy `SignupDetails` chunk is the lever: blocking it gives
 * the chunk-load failure (and offline, when the browser reports no network); replacing it with a
 * module that throws gives the error boundary, a 429 and a 503 through the real route
 * `errorElement`. A popover is rendered the same way, from the real `Popover` component.
 * Maintenance has no screen of its own in this app: a 503 ("Lemely is having trouble right now")
 * is its nearest state and is covered here.
 */
const CHUNK = '**/src/portals/auth/SignupDetails.tsx*'
const stub = (body: string) => (page: Page) =>
  page.route(CHUNK, (route) => route.fulfill({ contentType: 'text/javascript', body }))
const THROW = (expr: string) => `import { ApiError } from "/src/lib/api.ts"\nexport function SignupDetails() { throw ${expr} }`

const STATES: { name: string; text: RegExp; arm: (page: Page) => Promise<unknown>; offline?: boolean }[] = [
  { name: 'error boundary', text: /Something went wrong/, arm: stub(THROW('new Error("boom")')) },
  { name: '429', text: /Slow down for a moment/, arm: stub(THROW('new ApiError(429, "slow", undefined, 30)')) },
  { name: '503 (maintenance)', text: /having trouble right now/, arm: stub(THROW('new ApiError(503, "down")')) },
  { name: 'chunk-load failure', text: /couldn.t finish loading/, arm: (page) => page.route(CHUNK, (route) => route.abort()) },
  { name: 'offline', text: /You.re offline/, arm: (page) => page.route(CHUNK, (route) => route.abort()), offline: true },
]

async function openState(page: Page, s: (typeof STATES)[number]) {
  await page.route('**/api/**', (route) => {
    if (route.request().url().includes('/api/access/config')) return route.fulfill({ json: { restricted: false } })
    return route.fulfill({ status: 404, json: { detail: 'nf' } })
  })
  if (s.offline) await page.addInitScript(() => Object.defineProperty(navigator, 'onLine', { get: () => false }))
  await s.arm(page)
  await page.goto('/signup/student')
  await expect(page.getByText(s.text).first()).toBeVisible({ timeout: 15000 })
}

const axeViolations = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']).analyze()).violations.map((v) => v.id)

test.describe('state screens: anonymous visitor on a dark OS is light', () => {
  test.use({ colorScheme: 'dark' })
  for (const s of STATES) {
    test(s.name, async ({ page }) => {
      await openState(page, s)
      expect(await theme(page)).toBe('light')
      expect(await surfaceIsLight(page)).toBe(true)
      expect(await axeViolations(page)).toEqual([])
    })
  }
})

test.describe('state screens: signed-in dark user is dark', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((s) => {
      localStorage.setItem('lemely.session', JSON.stringify(s))
      localStorage.setItem('lemely.theme', 'dark')
    }, session)
  })
  for (const s of STATES) {
    test(s.name, async ({ page }) => {
      await openState(page, s)
      expect(await theme(page)).toBe('dark')
      expect(await surfaceIsLight(page)).toBe(false)
      expect(await axeViolations(page)).toEqual([])
    })
  }
})

test('signed-in dark: the student navigation drawer (a portalled overlay) is dark', async ({ page }) => {
  await page.addInitScript((s) => {
    localStorage.setItem('lemely.session', JSON.stringify(s))
    localStorage.setItem('lemely.theme', 'dark')
  }, session)
  await page.route('**/api/**', (route) => route.fulfill({ status: 404, json: {} }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/student')
  const trigger = page.getByRole('button', { name: 'Open student navigation' })
  await trigger.click()
  const popover = page.locator('[role="dialog"]').first()
  await expect(popover).toBeVisible()
  expect(lightnessOf(await popover.evaluate((e) => getComputedStyle(e).backgroundColor))).toBeLessThan(0.5)
})

/*
 * Public pages are a real surface in dark for a signed-in user (the roles flip; only what a flip
 * cannot fix is patched in `brand-tokens.css`), and light for everyone else. axe finds none in
 * either, on the landing, the data page, the tutor directory, coming soon, invite entry and the
 * verify-email screen.
 */
const PUBLIC_PAGES = ['/landing', '/data', '/tutors', '/coming-soon', '/join', '/verify-email']
for (const dark of [false, true]) {
  for (const path of PUBLIC_PAGES) {
    test(`axe: ${path} has no violations (${dark ? 'signed in, dark' : 'signed out, light'})`, async ({ page }) => {
      if (dark) {
        await page.addInitScript((s) => {
          localStorage.setItem('lemely.session', JSON.stringify(s))
          localStorage.setItem('lemely.theme', 'dark')
        }, session)
      }
      await page.route('**/api/**', (route) => {
        const url = route.request().url()
        if (url.includes('/api/access/config')) return route.fulfill({ json: { restricted: false } })
        if (url.includes('/api/public/tutors')) return route.fulfill({ json: { items: [], total: 0 } })
        return route.fulfill({ status: 404, json: {} })
      })
      await page.goto(path)
      await page.waitForTimeout(1500)
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y)
          await new Promise((r) => setTimeout(r, 40))
        }
        window.scrollTo(0, 0)
      })
      await page.waitForTimeout(900) // let scroll-triggered reveals finish: axe reads mid-fade colours
      expect(await theme(page)).toBe(dark ? 'dark' : 'light')
      expect(await axeViolations(page)).toEqual([])
    })
  }
}
