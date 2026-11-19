import { test, expect as baseExpect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/*
 * `/waitlist/confirm?token=…` (the link in the confirmation email) and the success copy that points
 * to it. Fully mocked; needs the vite server only.
 */
// The confirm page is a lazy chunk: the first request after a cold dev-server start compiles it.
const expect = baseExpect.configure({ timeout: 15_000 })
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const session = {
  accessToken: `${b64({ alg: 'none' })}.${b64({ exp: 4102444800 })}.x`,
  refreshToken: null,
  userId: 'u1',
  role: 'student',
}

type Reply = { status: number; json?: unknown } | 'abort'

/** Answers each POST /api/waitlist/confirm from the list in order (the last repeats) and records the bodies. */
async function mockConfirm(page: Page, replies: Reply[]) {
  const bodies: Record<string, unknown>[] = []
  await page.route('**/api/waitlist/config', (route) =>
    route.fulfill({ json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'Applying opts you in to Lemely emails.' } }),
  )
  await page.route('**/api/waitlist/confirm', (route) => {
    bodies.push(route.request().postDataJSON() as Record<string, unknown>)
    const reply = replies[Math.min(bodies.length - 1, replies.length - 1)]
    if (reply === 'abort') return route.abort()
    return route.fulfill({ status: reply.status, json: reply.json ?? {} })
  })
  return bodies
}

const ok = (status: 'confirmed' | 'already_confirmed'): Reply => ({ status: 200, json: { status } })
const bad = (code: string): Reply => ({ status: 400, json: { detail: { code } } })
const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const violations = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()).violations.map((v) => v.id)

test.describe('confirm page states', () => {
  test('confirmed: one request, the token leaves the address bar, Share and a way back', async ({ page }) => {
    const bodies = await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
    await expect(page).toHaveURL(/\/waitlist\/confirm$/)
    expect(bodies).toEqual([{ token: 'abc123' }])
    await expect(page.getByRole('button', { name: 'Share Lemely' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Back to the landing page' })).toHaveAttribute('href', '/landing')
    expect(await violations(page)).toEqual([])
  })

  test('Share falls back to copying the landing link', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.addInitScript(() => Object.defineProperty(navigator, 'share', { value: undefined }))
    await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await page.getByRole('button', { name: 'Share Lemely' }).click()
    await expect(page.getByRole('button', { name: 'Link copied' })).toBeVisible()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toMatch(/\/landing\?utm_source=waitlist_share/)
  })

  test('Binny reacts to a tap (expression changes, bubble goes) and starts happy when confirmed', async ({ page }) => {
    await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
    const binny = page.locator('.cs-binny')
    await expect(binny).toHaveAttribute('data-mood', 'happy')
    await expect(page.getByText('Nice one.')).toBeVisible()
    await page.getByRole('button', { name: 'Say hi to Binny' }).click()
    await expect(binny).toHaveAttribute('data-mood', 'wink')
    await expect(page.getByText('Nice one.')).toHaveCount(0)
  })

  test('each failure has its own Binny mood and line', async ({ page }) => {
    await mockConfirm(page, [bad('invalid_token')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(page.getByText('Hmm, not this one.')).toBeVisible()
    await expect(page.locator('.cs-binny')).toHaveAttribute('data-mood', 'thinking')
  })

  test('already confirmed', async ({ page }) => {
    await mockConfirm(page, [ok('already_confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Already confirmed.')
    await expect(page.getByRole('button', { name: 'Share Lemely' })).toHaveCount(0)
    expect(await violations(page)).toEqual([])
  })

  for (const [code, title] of [
    ['invalid_token', "That link doesn't work."],
    ['expired_token', 'That link has expired.'],
  ] as const) {
    test(`${code}: tells them to re-enter their email, and the CTA opens the waitlist`, async ({ page }) => {
      await mockConfirm(page, [bad(code)])
      await page.goto('/waitlist/confirm?token=abc123')
      await expect(h1(page)).toHaveText(title)
      await expect(page.getByText(/Enter your email on the waitlist form again/)).toBeVisible()
      expect(await violations(page)).toEqual([])
      const cta = page.getByRole('main').getByRole('button', { name: 'Join the waitlist' })
      await cta.click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await expect(cta).toBeFocused()
    })
  }

  test('a missing token is an invalid link and makes no request', async ({ page }) => {
    const bodies = await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm')
    await expect(h1(page)).toHaveText("That link doesn't work.")
    expect(bodies).toEqual([])
  })

  test('rate limited: Try again asks once more', async ({ page }) => {
    const bodies = await mockConfirm(page, [{ status: 429, json: { detail: 'slow' } }, ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Slow down a little.')
    expect(await violations(page)).toEqual([])
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
    expect(bodies).toEqual([{ token: 'abc123' }, { token: 'abc123' }])
  })

  test('network failure: Try again asks once more', async ({ page }) => {
    await mockConfirm(page, ['abort', ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Binny lost the signal.')
    expect(await violations(page)).toEqual([])
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
  })

  test('is public: reachable while access is restricted, signed out', async ({ page }) => {
    await page.route('**/api/access/config', (route) => route.fulfill({ json: { restricted: true } }))
    await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
  })
})

test.describe('confirm page theme', () => {
  test.use({ colorScheme: 'dark' })
  test('light for a signed-out visitor on a dark OS', async ({ page }) => {
    await mockConfirm(page, [ok('confirmed')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('Confirmed. Binny approves.')
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('light')
    expect(await violations(page)).toEqual([])
  })

  test('dark for a signed-in user on a dark theme, axe clean', async ({ page }) => {
    await page.addInitScript((s) => {
      localStorage.setItem('lemely.session', JSON.stringify(s))
      localStorage.setItem('lemely.theme', 'dark')
    }, session)
    await mockConfirm(page, [bad('expired_token')])
    await page.goto('/waitlist/confirm?token=abc123')
    await expect(h1(page)).toHaveText('That link has expired.')
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark')
    expect(await violations(page)).toEqual([])
  })
})

test.describe('the form around it', () => {
  async function openForm(page: Page, joinReply: unknown) {
    await page.route('**/api/waitlist/config', (route) =>
      route.fulfill({ json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'x' } }),
    )
    await page.route('**/api/waitlist', (route) =>
      route.request().method() === 'POST' ? route.fulfill({ json: joinReply as never }) : route.fulfill({ json: { status: 'completed' } }),
    )
    await page.goto('/landing')
    await page.locator('.brand-hero .brand-actions button').click()
    return page.getByRole('dialog')
  }
  const fill = async (dialog: ReturnType<Page['getByRole']>) => {
    await dialog.getByLabel('Email').fill('student@example.com')
    await dialog.getByLabel('Full name').fill('Sam Student')
    await dialog.getByText('Student', { exact: true }).click()
    await dialog.getByRole('button', { name: /Continue/ }).click()
  }

  test('the name placeholder is "Your Name"', async ({ page }) => {
    const dialog = await openForm(page, { status: 'created', token: 't' })
    await expect(dialog.getByLabel('Full name')).toHaveAttribute('placeholder', 'Your Name')
  })

  test('success tells them to check their inbox and confirm', async ({ page }) => {
    const dialog = await openForm(page, { status: 'created', token: 't' })
    await fill(dialog)
    await dialog.getByRole('button', { name: 'Biology' }).click()
    await dialog.getByRole('button', { name: 'Join the waitlist' }).click()
    await expect(dialog.getByText("You're on the list, Sam")).toBeVisible()
    await expect(dialog.getByText(/Check your inbox and open it to confirm your email/)).toBeVisible()
  })

  test('already on the list says a fresh link was sent', async ({ page }) => {
    const dialog = await openForm(page, { status: 'already_listed' })
    await fill(dialog)
    await expect(dialog.getByText(/already on the list\. We've sent a fresh link: check your inbox/)).toBeVisible()
  })
})
