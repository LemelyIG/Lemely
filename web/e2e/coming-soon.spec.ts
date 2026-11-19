import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/*
 * Pre-launch access gate, fully mocked: it needs the vite server only. Covers the coming-soon
 * screen on the sign-in/signup entry points, the team sign-in path, config-failure behaviour and
 * a 403 `access_restricted` on an app route ending the session.
 */
const TITLE = 'Almost ready. Say hi.'

async function config(page: Page, restricted: boolean | 'fail') {
  await page.route('**/api/access/config', (route) =>
    restricted === 'fail'
      ? route.fulfill({ status: 500, json: { detail: 'boom' } })
      : route.fulfill({ json: { restricted } }),
  )
  await page.route('**/api/waitlist/config', (route) =>
    route.fulfill({ json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'Applying opts you in to Lemely emails.' } }),
  )
}

for (const path of ['/login', '/signup', '/signup/student', '/signup/teacher', '/signup/parent', '/join']) {
  test(`restricted: ${path} shows coming soon, not the form`, async ({ page }) => {
    await config(page, true)
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
    await expect(page.locator('input[type="password"]')).toHaveCount(0)
  })
}

test('restricted: coming soon is axe-clean, opens the waitlist and returns focus to the CTA', async ({ page }) => {
  await config(page, true)
  await page.goto('/signup')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']).analyze()
  expect(results.violations).toEqual([])
  const cta = page.getByRole('button', { name: 'Join the waitlist' })
  await cta.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(cta).toBeFocused()
  await expect(page.getByRole('link', { name: 'Back to the landing page', exact: true })).toHaveAttribute('href', '/')
})

test('restricted: tapping Binny reacts; the bubble goes away', async ({ page }) => {
  await config(page, true)
  await page.goto('/login')
  await expect(page.getByText('Tap me.')).toBeVisible()
  const binny = page.locator('.cs-binny')
  await expect(binny).toHaveAttribute('data-mood', 'open')
  await page.getByRole('button', { name: 'Say hi to Binny' }).click()
  await expect(binny).toHaveAttribute('data-mood', 'happy')
  await expect(page.getByText('Tap me.')).toHaveCount(0)
})

test('unrestricted: the real forms render', async ({ page }) => {
  await config(page, false)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.goto('/signup')
  await expect(page.getByRole('heading', { level: 1 })).not.toHaveText(TITLE)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('team sign-in: reached from coming soon, shows the real login form while restricted', async ({ page }) => {
  await config(page, true)
  await page.goto('/login')
  await page.getByRole('link', { name: 'Team sign-in' }).click()
  await expect(page).toHaveURL(/\/login\?team=1$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(1)
})

test('config call fails: signup fails closed, login still shows the form', async ({ page }) => {
  await config(page, 'fail')
  await page.goto('/signup')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})

test('the landing header links still point at /login and /signup', async ({ page }) => {
  await config(page, true)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/landing')
  await expect(page.getByRole('link', { name: 'Sign in' }).first()).toHaveAttribute('href', '/login')
  await expect(page.getByRole('link', { name: 'Sign up' }).first()).toHaveAttribute('href', '/signup')
})

test('403 access_restricted on an app route ends the session and shows coming soon', async ({ page }) => {
  await config(page, true)
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
  const session = {
    accessToken: `${b64({ alg: 'none' })}.${b64({ exp: 4102444800 })}.x`,
    refreshToken: null,
    userId: 'u1',
    role: 'student',
  }
  await page.addInitScript((s) => localStorage.setItem('lemely.session', JSON.stringify(s)), session)
  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/access/config') || url.includes('/api/waitlist')) return route.fallback()
    return route.fulfill({ status: 403, json: { detail: { code: 'access_restricted', reason: 'domain' } } })
  })
  await page.goto('/student')
  await expect(page).toHaveURL(/\/coming-soon$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  expect(await page.evaluate(() => localStorage.getItem('lemely.session'))).toBeNull()
})

test('403 access_restricted with reason unverified goes to the verify-email flow and keeps the session', async ({ page }) => {
  await config(page, true)
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
  const session = {
    accessToken: `${b64({ alg: 'none' })}.${b64({ exp: 4102444800 })}.x`,
    refreshToken: null,
    userId: 'u1',
    role: 'student',
  }
  await page.addInitScript((s) => localStorage.setItem('lemely.session', JSON.stringify(s)), session)
  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/access/config') || url.includes('/api/waitlist')) return route.fallback()
    if (url.includes('/api/auth/')) return route.fulfill({ status: 200, json: {} })
    return route.fulfill({ status: 403, json: { detail: { code: 'access_restricted', reason: 'unverified' } } })
  })
  await page.goto('/student')
  await expect(page).toHaveURL(/\/verify-email$/)
  expect(await page.evaluate(() => localStorage.getItem('lemely.session'))).not.toBeNull()
})

/*
 * F1: new team accounts must be creatable while access is restricted. `?team=1` opens the real
 * sign-in and sign-up forms and is carried between them; a non-allowed address is refused by the
 * backend and the form shows it inline instead of throwing the visitor to coming soon.
 */
const REFUSAL = { status: 403, json: { detail: { code: 'access_restricted', reason: 'domain' } } }

test('team sign-up is reachable while restricted, and the team flag follows the links', async ({ page }) => {
  await config(page, true)
  await page.goto('/login')
  await page.getByRole('link', { name: 'Team sign-up' }).click()
  await expect(page).toHaveURL(/\/signup\?team=1$/)
  await expect(page.getByText("I'm a student")).toBeVisible()
  await page.getByRole('link', { name: /I'm a student/ }).click()
  await expect(page).toHaveURL(/\/signup\/student\?team=1$/)
  await expect(page.getByLabel('Email')).toBeVisible()
  await page.getByRole('link', { name: 'Sign in' }).first().click()
  await expect(page).toHaveURL(/\/login\?team=1$/)
  await page.getByRole('link', { name: 'Create an account' }).click()
  await expect(page).toHaveURL(/\/signup\?team=1$/)
})

test('without the team flag the signup routes still show coming soon', async ({ page }) => {
  await config(page, true)
  for (const path of ['/signup', '/signup/student', '/signup/teacher']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(TITLE)
  }
})

test('a non-allowed address on team sign-in shows the refusal inline and stays on the page', async ({ page }) => {
  await config(page, true)
  await page.route('**/api/auth/login', (route) => route.fulfill(REFUSAL))
  await page.goto('/login?team=1')
  await page.getByLabel('Email').fill('someone@example.com')
  await page.locator('input[type="password"]').fill('correct horse battery')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText("Lemely isn't open yet. Only team accounts can sign in right now.")).toBeVisible()
  await expect(page).toHaveURL(/\/login\?team=1$/)
})

test('a non-allowed address on team sign-up shows the refusal inline and stays on the page', async ({ page }) => {
  await config(page, true)
  await page.route('**/api/auth/signup', (route) => route.fulfill(REFUSAL))
  await page.goto('/signup/student?team=1')
  await page.getByLabel('Name').fill('Sam Student')
  await page.getByLabel('Email').fill('someone@example.com')
  await page.getByLabel('Password', { exact: false }).first().fill('correct horse battery')
  await page.locator('#signup-consent').check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByText("Lemely isn't open yet. Only team accounts can sign up right now.")).toBeVisible()
  await expect(page).toHaveURL(/\/signup\/student\?team=1$/)
})
