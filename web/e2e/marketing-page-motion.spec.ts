import { test, expect } from '@playwright/test'

test.use({ contextOptions: { reducedMotion: 'no-preference' } })

test('proof figures count up once and reduced motion keeps the final values', async ({
  page,
}) => {
  await page.goto('/landing')
  const proof = page.locator('.brand-proof')
  const counted = proof.evaluate(
    (el) =>
      new Promise<string[]>((resolve, reject) => {
        const values: string[] = []
        const counter = el.querySelector('.brand-metric strong')!
        const timer = setTimeout(() => {
          observer.disconnect()
          reject(new Error('No visible proof count-up'))
        }, 4000)
        const observer = new MutationObserver(() => {
          values.push(
            el.querySelector('.brand-metric strong')!.textContent || '',
          )
          if (
            values.some((value) => value !== '11,000+') &&
            values.at(-1) === '11,000+'
          ) {
            clearTimeout(timer)
            observer.disconnect()
            resolve(values)
          }
        })
        observer.observe(counter.parentElement!, {
          subtree: true,
          childList: true,
          characterData: true,
        })
        el.scrollIntoView({ behavior: 'instant', block: 'start' })
      }),
  )
  const papers = proof.locator('.brand-metric strong').first()
  expect((await counted).some((value) => value !== '11,000+')).toBe(true)
  await expect(papers).toHaveText('11,000+', { timeout: 4000 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(proof.locator('.brand-metric strong').nth(2)).toHaveText(
    '+2.5 grades',
  )
})

test('Binny thinks, answers, and returns to idle without blocking other questions', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/landing#faq')
  await page
    .getByRole('button', { name: 'How accurate is the AI marking?' })
    .click()
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toContainText('THINKING')
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toContainText('Very. In blind tests', { timeout: 4000 })
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toContainText('READY TO HELP')
  await page.getByRole('button', { name: 'Can parents see results?' }).click()
  await expect(
    page.getByRole('region', { name: 'Binny answers' }),
  ).toContainText('Parents get their own live dashboard', { timeout: 4000 })
})

test('mobile upload shortcut follows scrolling and disappears at the closing action', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/landing')
  const upload = page.getByRole('link', { name: 'Upload free', exact: true })
  await expect(upload).toHaveAttribute('href', '/signup')
  await page.locator('#features').scrollIntoViewIfNeeded()
  await page.mouse.wheel(0, -100)
  await expect(upload).toBeVisible()
  await page.locator('#start').scrollIntoViewIfNeeded()
  await expect(upload).not.toBeVisible()
})

test('mobile feature deck exposes every feature and announces its position', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/landing#features')
  const deck = page.getByRole('region', { name: 'Lemely features' })
  await expect(deck.getByRole('status')).toHaveText('1 / 8')
  await deck.getByRole('button', { name: 'Next card' }).click()
  await expect(deck.getByRole('status')).toHaveText('2 / 8')
  await expect(
    deck.getByRole('heading', { name: 'Confidence on every mark' }),
  ).toBeInViewport()
  await deck
    .getByRole('group', { name: 'Lemely features cards' })
    .press('ArrowLeft')
  await expect(deck.getByRole('status')).toHaveText('1 / 8')
})
