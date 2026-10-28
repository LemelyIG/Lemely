import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('matches the dark teacher band and desktop Binny conversation', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/landing')
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Can parents see results?' }).click()
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toContainText('Parents get their own live dashboard')
  const colors = await page.evaluate(() =>
    ['.brand-proof', '.brand-teachers'].map(
      (s) => getComputedStyle(document.querySelector(s)!).backgroundColor,
    ),
  )
  expect(colors[0]).toBe(colors[1])
})

test('public landing preserves destinations and reference sections', async ({
  page,
}) => {
  await page.goto('/landing')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Every mark, explained.',
  )
  await expect(page.getByRole('main')).toHaveCount(1)
  for (const id of ['teachers', 'how', 'features', 'faq', 'start'])
    await expect(page.locator(`#${id}`)).toBeAttached()
  await expect(
    page.getByRole('link', { name: 'Upload your first paper free' }).first(),
  ).toHaveAttribute('href', '/signup')
  await expect(page.getByText('98.7%', { exact: false }).first()).toBeVisible()
  await page.getByRole('link', { name: 'How your data is handled' }).click()
  await expect(page).toHaveURL(/\/data$/)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('walkthrough, review and FAQ work with the keyboard', async ({ page }) => {
  await page.goto('/landing')
  const mobile = await page.evaluate(() => innerWidth < 760)
  if (!mobile) await page.getByRole('tab', { name: /02 Marked/ }).click()
  await page.getByRole('tab', { name: /Q3\(c\)/ }).click()
  await expect(page.getByText('AI confidence 72%')).toBeVisible()
  await page.getByRole('radio', { name: 'Award A1' }).click()
  await expect(page.getByText('Illustration: A1 awarded')).toBeVisible()
  if (!mobile) await page.getByRole('tab', { name: /03 Insights/ }).click()
  else await page.getByText('Weak topic found').scrollIntoViewIfNeeded()
  await expect(page.getByText('Weak topic found')).toBeVisible()
  const faq = page.getByRole('button', {
    name: 'How accurate is the AI marking?',
  })
  await faq.focus()
  await page.keyboard.press('Enter')
  await expect(faq).toHaveAttribute('aria-expanded', 'true')
  await expect(
    page.getByText('Very. In blind tests', { exact: false }),
  ).toBeVisible()
  await page
    .getByRole('textbox', { name: 'Ask anything else' })
    .fill('Can we arrange a demo?')
  await expect(page.getByRole('link', { name: 'Open email' })).toHaveAttribute(
    'href',
    /mailto:contact@lemelyig.com.*Can%20we/,
  )
})

test('responsive layout and accessible mobile navigation', async ({
  page,
}, testInfo) => {
  await page.goto('/landing')
  for (const width of [320, 375, 390, 414, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 950 })
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    const clippedHeadings = await page
      .locator('.brand-landing h1,.brand-landing h2')
      .evaluateAll((headings) =>
        headings
          .filter((heading) => heading.scrollWidth > heading.clientWidth + 1)
          .map((heading) => heading.textContent),
      )
    expect(clippedHeadings).toEqual([])
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open menu' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page
    .getByRole('dialog')
    .getByRole('link', { name: 'Features', exact: true })
    .click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations).toEqual([])
  await page.screenshot({
    path: testInfo.outputPath('landing-mobile.png'),
    fullPage: true,
  })
})
