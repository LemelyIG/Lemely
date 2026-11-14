import { test, expect } from '@playwright/test'

/* Every signed-out auth screen can get back to the landing page. Mocked: vite server only. */
const PATHS = ['/login', '/signup', '/signup/student', '/signup/teacher', '/signup/parent', '/verify-email', '/reset', '/join']

for (const path of PATHS) {
  test(`${path}: back link and wordmark return to the landing page`, async ({ page }) => {
    await page.route('**/api/access/config', (r) => r.fulfill({ json: { restricted: false } }))
    await page.goto(path)
    const back = page.getByTestId('auth-back-home')
    await expect(back).toBeVisible()
    await expect(back).toHaveAttribute('href', '/')
    await expect(page.getByTestId('auth-wordmark-link')).toHaveAttribute('href', '/')
    await back.click()
    await expect(page).toHaveURL(/\/$/)
  })
}
