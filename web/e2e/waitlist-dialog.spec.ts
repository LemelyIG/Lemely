import { test, expect } from '@playwright/test'

/*
 * Landing waitlist dialog, Back then Continue. Fully mocked (config, POST, PATCH): it needs the
 * vite server only. Component behaviour lives here, not in vitest (node environment, no jsdom).
 *
 * Once step 1 succeeds the panel holds a one-time token, so Back then Continue must go straight
 * to step 2. A second POST would answer "already listed", skip step 2 and lose the picked subjects.
 */
test('Back then Continue sends one POST and keeps the picked subject', async ({ page }) => {
  let posts = 0
  await page.route('**/api/waitlist/config', (route) =>
    route.fulfill({
      json: { turnstileSiteKey: null, consentVersion: 'v', consentText: 'Applying opts you in to Lemely emails.' },
    }),
  )
  await page.route('**/api/waitlist', (route) => {
    if (route.request().method() === 'POST') {
      posts += 1
      return route.fulfill({ json: { status: 'created', token: 'one-time-token' } })
    }
    return route.fulfill({ json: { status: 'completed' } })
  })

  await page.goto('/landing')
  await page.locator('.brand-hero .brand-actions button').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email').fill('student@example.com')
  await dialog.getByLabel('Full name').fill('Sam Student')
  await dialog.getByText('Student', { exact: true }).click()
  await dialog.getByRole('button', { name: /Continue/ }).click()

  await expect(dialog.getByText('Which subjects do you study?')).toBeVisible()
  const biology = dialog.getByRole('button', { name: 'Biology' })
  await biology.click()
  await expect(biology).toHaveAttribute('aria-pressed', 'true')
  expect(posts).toBe(1)

  await dialog.getByRole('button', { name: 'Back to email and role' }).click()
  await dialog.getByRole('button', { name: /Continue/ }).click()

  await expect(dialog.getByText('Which subjects do you study?')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Biology' })).toHaveAttribute('aria-pressed', 'true')
  expect(posts).toBe(1)
})
