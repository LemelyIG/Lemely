import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/*
 * Waitlist: the required Full name on step 1, and the admin queue's Name column and detail sheet.
 * Fully mocked; needs the vite server only.
 */
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const adminSession = {
  accessToken: `${b64({ alg: 'none' })}.${b64({ exp: 4102444800 })}.x`,
  refreshToken: null,
  userId: 'u1',
  role: 'platform_admin',
}

async function mockPublic(page: Page, onPost?: (body: Record<string, unknown>) => unknown) {
  await page.route('**/api/waitlist/config', (route) =>
    route.fulfill({ json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'Applying opts you in to Lemely emails.' } }),
  )
  await page.route('**/api/waitlist', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const custom = onPost?.(body)
      if (custom) return route.fulfill(custom as never)
      return route.fulfill({ json: { status: 'created', token: 'one-time-token' } })
    }
    return route.fulfill({ json: { status: 'completed' } })
  })
}

async function openForm(page: Page) {
  await page.goto('/landing')
  await page.locator('.brand-hero .brand-actions button').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Full name')).toBeVisible()
  return dialog
}

test.describe('step 1: Full name', () => {
  test('is the second field, between email and role, with autocomplete=name', async ({ page }) => {
    await mockPublic(page)
    const dialog = await openForm(page)
    const name = dialog.getByLabel('Full name')
    await expect(name).toHaveAttribute('autocomplete', 'name')
    const order = await dialog.evaluate((root) => {
      const q = (sel: string) => root.querySelector(sel)
      const email = q('input[type="email"]')!
      const name = q('input[autocomplete="name"]')!
      const role = q('.lw-roles')!
      const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
      return before(email, name) && before(name, role)
    })
    expect(order).toBe(true)
  })

  test('is required: Continue without it shows the error inline and sends nothing', async ({ page }) => {
    let posts = 0
    await mockPublic(page, () => void (posts += 1))
    const dialog = await openForm(page)
    await dialog.getByLabel('Email').fill('student@example.com')
    await dialog.getByText('Student', { exact: true }).click()
    await dialog.getByRole('button', { name: /Continue/ }).click()
    await expect(dialog.getByText('Enter your full name.')).toBeVisible()
    expect(posts).toBe(0)
  })

  test('validates on blur: too long is flagged, empty stays quiet until submit', async ({ page }) => {
    await mockPublic(page)
    const dialog = await openForm(page)
    const name = dialog.getByLabel('Full name')
    await name.focus()
    await name.blur()
    await expect(dialog.getByText('Enter your full name.')).toHaveCount(0)
    await name.fill('x'.repeat(101))
    await name.blur()
    await expect(dialog.getByText('Use 100 characters or fewer.')).toBeVisible()
    await name.fill('Sam Student')
    await expect(dialog.getByText('Use 100 characters or fewer.')).toHaveCount(0)
  })

  test('sends the trimmed, collapsed name; a server 422 on name shows inline', async ({ page }) => {
    const bodies: Record<string, unknown>[] = []
    await mockPublic(page, (body) => {
      bodies.push(body)
      if (bodies.length === 1) {
        return {
          status: 422,
          json: { detail: [{ loc: ['body', 'name'], msg: 'Value error, That name looks empty.', type: 'value_error' }] },
        }
      }
      return undefined
    })
    const dialog = await openForm(page)
    await dialog.getByLabel('Email').fill('student@example.com')
    await dialog.getByLabel('Full name').fill('  Sam    Student ')
    await dialog.getByText('Student', { exact: true }).click()
    await dialog.getByRole('button', { name: /Continue/ }).click()
    await expect(dialog.getByText('That name looks empty.')).toBeVisible()
    expect(bodies[0].name).toBe('Sam Student')
    await dialog.getByRole('button', { name: /Continue/ }).click()
    await expect(dialog.getByText('Which subjects do you study?')).toBeVisible()
  })

  test('the success state greets by first name', async ({ page }) => {
    await mockPublic(page)
    const dialog = await openForm(page)
    await dialog.getByLabel('Email').fill('student@example.com')
    await dialog.getByLabel('Full name').fill('Sam Student')
    await dialog.getByText('Student', { exact: true }).click()
    await dialog.getByRole('button', { name: /Continue/ }).click()
    await dialog.getByRole('button', { name: 'Biology' }).click()
    await dialog.getByRole('button', { name: 'Join the waitlist' }).click()
    await expect(dialog.getByText("You're on the list, Sam")).toBeVisible()
  })

  test('axe: the form is clean, signed out (light) and signed in (dark)', async ({ page }) => {
    await mockPublic(page)
    const dialog = await openForm(page)
    expect((await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()).violations.map((v) => v.id)).toEqual([])
    await expect(dialog).toBeVisible()
  })

  test('axe: the form is clean for a signed-in user on a dark theme', async ({ page }) => {
    await page.addInitScript((s) => {
      localStorage.setItem('lemely.session', JSON.stringify(s))
      localStorage.setItem('lemely.theme', 'dark')
    }, adminSession)
    await mockPublic(page)
    await page.route('**/api/me/**', (route) => route.fulfill({ status: 404, json: {} }))
    await openForm(page)
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark')
    // The dialog only: the landing's art behind it has its own dark-theme contrast findings (reported separately).
    expect((await new AxeBuilder({ page }).include('[role="dialog"]').withTags(AXE_TAGS).analyze()).violations.map((v) => v.id)).toEqual([])
  })
})

/* ---------------------------------------------------------------- admin queue */

const applicant = (i: number, over: Record<string, unknown> = {}) => ({
  id: `id-${i}`,
  email: `person${i}@example.com`,
  name: `Person Number ${i}`,
  role: 'student',
  centreName: null,
  levels: ['o_level'],
  subjects: ['biology'],
  otherSubjects: ['Robotics'],
  examBoards: ['caie'],
  examSession: '2027-mj',
  phone: '+201000000001',
  phoneHasWhatsapp: true,
  emailConfirmed: true,
  emailConfirmedAt: '2026-11-09T10:00:00Z',
  consentVersion: '2026-11-v1',
  consentText: 'Applying opts you in to Lemely emails.',
  consentAt: '2026-11-08T07:41:00Z',
  status: 'new',
  adminNote: null,
  utmSource: 'waitlist_share',
  utmMedium: 'share',
  utmCampaign: 'launch',
  utmContent: null,
  utmTerm: null,
  completedAt: '2026-11-08T07:45:00Z',
  partial: false,
  createdAt: '2026-11-08T07:41:00Z',
  updatedAt: '2026-11-08T07:45:00Z',
  ...over,
})
const ITEMS = [applicant(1), applicant(2, { name: null, phone: null, phoneHasWhatsapp: false }), applicant(3)]

async function openAdmin(page: Page, dark = false) {
  await page.addInitScript(
    ([s, d]) => {
      localStorage.setItem('lemely.session', JSON.stringify(s))
      if (d) localStorage.setItem('lemely.theme', 'dark')
    },
    [adminSession, dark] as const,
  )
  const patches: Record<string, unknown>[] = []
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/admin/waitlist')
      return route.fulfill({
        json: { items: ITEMS, total: 3, page: 1, pageSize: 50, counts: { all: 3, new: 3, contacted: 0, invited: 0, declined: 0, partial: 0 } },
      })
    const one = url.pathname.match(/^\/api\/admin\/waitlist\/([^/]+)$/)
    if (one && route.request().method() === 'PATCH') {
      patches.push(route.request().postDataJSON())
      return route.fulfill({ json: ITEMS.find((i) => i.id === one[1]) })
    }
    if (url.pathname === '/api/me/profile')
      return route.fulfill({ json: { displayName: 'Admin', email: 'admin@example.com', role: 'platform_admin', emailVerified: true, avatarUrl: null } })
    return route.fulfill({ status: 404, json: {} })
  })
  await page.goto('/platform/waitlist')
  await expect(page.getByRole('heading', { name: 'Waitlist', level: 1 })).toBeVisible()
  return patches
}

test.describe('admin queue', () => {
  test('the table starts with a Name column: names, and a dash for rows with none', async ({ page }) => {
    await openAdmin(page)
    const headers = await page.getByRole('columnheader').allTextContents()
    expect(headers[0].trim()).toBe('Name')
    await expect(page.locator('tr[data-row-id="id-1"] td').first()).toHaveText('Person Number 1')
    await expect(page.locator('tr[data-row-id="id-2"] td').first()).toHaveText('-')
  })

  test('a row opens a sheet with every group; status and note stay editable', async ({ page }) => {
    const patches = await openAdmin(page)
    await page.locator('tr[data-row-id="id-1"]').click()
    const sheet = page.getByRole('dialog')
    await expect(sheet).toBeVisible()
    await expect(sheet.getByRole('heading', { name: 'Person Number 1' })).toBeVisible()
    for (const group of ['Applicant', 'Study', 'Contact', 'Consent', 'Source', 'Record']) {
      await expect(sheet.getByRole('heading', { name: group, level: 3 })).toBeVisible()
    }
    for (const label of ['Other subjects', 'Exam boards', 'Exam session', 'WhatsApp', 'Email confirmed', 'Confirmed at', 'Wording', 'utm_medium', 'utm_campaign', 'Updated', 'Completed', 'ID']) {
      await expect(sheet.getByText(label, { exact: true })).toBeVisible()
    }
    await expect(sheet.getByRole('button', { name: 'Copy email' })).toBeVisible()
    await expect(sheet.getByRole('button', { name: 'Copy phone' })).toBeVisible()
    await sheet.getByLabel('Status').selectOption('contacted')
    await sheet.getByLabel('Note').fill('Called on Monday')
    await sheet.getByLabel('Note').blur()
    await expect.poll(() => patches.length).toBe(2)
    expect(patches).toEqual([{ status: 'contacted' }, { adminNote: 'Called on Monday' }])
  })

  test('j and k move between applicants while the sheet stays open; Esc closes and the row regains focus', async ({ page }) => {
    await openAdmin(page)
    await page.locator('tr[data-row-id="id-1"]').click()
    const sheet = page.getByRole('dialog')
    await expect(sheet.getByRole('heading', { name: 'Person Number 1' })).toBeVisible()
    await page.keyboard.press('j')
    await expect(sheet.getByRole('heading', { name: 'No name given' })).toBeVisible()
    await page.keyboard.press('j')
    await expect(sheet.getByRole('heading', { name: 'Person Number 3' })).toBeVisible()
    await page.keyboard.press('k')
    await expect(sheet.getByRole('heading', { name: 'No name given' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(sheet).toHaveCount(0)
    await expect(page.locator('tr[data-row-id="id-2"]')).toBeFocused()
  })

  for (const dark of [false, true]) {
    test(`axe: the table and the sheet are clean (${dark ? 'dark' : 'light'})`, async ({ page }) => {
      await openAdmin(page, dark)
      expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(dark ? 'dark' : 'light')
      const table = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
      expect(table.violations.map((v) => v.id)).toEqual([])
      await page.locator('tr[data-row-id="id-1"]').click()
      await expect(page.getByRole('dialog')).toBeVisible()
      const sheet = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
      expect(sheet.violations.map((v) => v.id)).toEqual([])
    })
  }
})
