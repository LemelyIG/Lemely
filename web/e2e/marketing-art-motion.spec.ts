import { expect, test } from '@playwright/test'

test('hero draws the chart, advances grade and lets Binny celebrate', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/landing')
  const chart = page.locator('[data-art-scene="hero"]')
  await chart.scrollIntoViewIfNeeded()
  await expect(chart).toHaveAttribute('data-motion', 'running')
  const clip = chart.locator('#hcClip rect')
  const first = Number(await clip.getAttribute('width'))
  await expect
    .poll(async () => Number(await clip.getAttribute('width')))
    .toBeGreaterThan(first + 20)
  await expect(page.locator('.brand-predicted b')).toHaveText('A*', {
    timeout: 10000,
  })
  await chart.locator('[data-hc="binny"]').focus()
  await page.keyboard.press('Enter')
  await expect
    .poll(async () =>
      Number(await chart.locator('[data-hc="lvl"]').getAttribute('opacity')),
    )
    .toBeGreaterThan(0)
})

test('feature artwork has distinct drawing, grade, clustering and bar motion', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/landing')
  for (const name of [
    'marking',
    'confidence',
    'predicted',
    'clusters',
    'trends',
    'plan',
    'xp',
    'content',
  ]) {
    const art = page.locator(`[data-art-scene="${name}"]`)
    await art.scrollIntoViewIfNeeded()
    await expect(art).toHaveAttribute('data-motion', 'running')
    await expect
      .poll(() =>
        art.evaluate((el) => el.getAnimations({ subtree: true }).length),
      )
      .toBeGreaterThan(0)
  }
  if ((page.viewportSize()?.width ?? 0) >= 760) {
    const items = page.locator(
      '.brand-feature-grid [data-slot="carousel-item"]',
    )
    const last = await items.last().boundingBox()
    const previous = await items.nth(6).boundingBox()
    expect(last!.width).toBeGreaterThan(previous!.width * 1.7)
  }
})

test('live reduced motion restores the complete chart and artwork', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/landing')
  await page.locator('[data-art-scene="hero"]').scrollIntoViewIfNeeded()
  await expect(page.locator('[data-art-scene="hero"]')).toHaveAttribute(
    'data-motion',
    'running',
  )
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('[data-art-scene="hero"]')).toHaveAttribute(
    'data-motion',
    'static',
  )
  await expect(page.locator('#hcClip rect')).toHaveAttribute('width', '640')
  await expect(page.locator('.brand-predicted b')).toHaveText('A*')
  await expect(page.locator('[data-hc="binny"]')).toHaveAttribute(
    'transform',
    'translate(528 0)',
  )
  await page.locator('[data-hc="binny"]').focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('[data-hc="lvl"]')).toHaveAttribute('opacity', '1')
  await expect(page.locator('[data-hc="binny"]')).toHaveAttribute(
    'transform',
    'translate(528 0)',
  )
})

test('feature timelines pause outside the viewport and restore complete artwork on reduction', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/landing')
  const art = page.locator('[data-art-scene="confidence"]')
  await art.scrollIntoViewIfNeeded()
  await expect(art).toHaveAttribute('data-motion', 'running')
  await page.locator('#start').scrollIntoViewIfNeeded()
  await expect(art).toHaveAttribute('data-motion', 'static')
  expect(
    await art.evaluate((el) =>
      el
        .getAnimations({ subtree: true })
        .every((a) => a.playState === 'paused' || a.playState === 'finished'),
    ),
  ).toBe(true)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await art.scrollIntoViewIfNeeded()
  await expect
    .poll(() =>
      art.evaluate((el) => el.getAnimations({ subtree: true }).length),
    )
    .toBe(0)
  await expect(art).toContainText('96%')
  await expect(art).toContainText('TEACHER REVIEW')
})
