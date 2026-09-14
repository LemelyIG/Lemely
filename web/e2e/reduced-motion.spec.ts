import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * P5.10 · The `prefers-reduced-motion` proof (BUILD/MISSION.md §4, Phase 5:
 * "Motion added in this phase must respect `prefers-reduced-motion`, proven
 * by a test").
 *
 * WHAT THIS TASK IS NOT. It is not a CSS task. The blanket rule already
 * exists at `src/index.css:742` — `@media (prefers-reduced-motion: reduce)`
 * over `*`, `*::before`, `*::after`, forcing `animation-duration: 0.001ms`,
 * `animation-iteration-count: 1` and `transition-duration: 0.001ms`, all
 * `!important` — and it genuinely reaches every animation in this app,
 * because the whole surface is CSS-only: three `@keyframes`, no animation
 * library, no `requestAnimationFrame`, no smooth scrolling. The gap was that
 * **no test in any suite had ever asserted it**, so "we respect reduced
 * motion" rested entirely on a CSS block nobody was checking still existed.
 * This file is that check and nothing more.
 *
 * WHY IT ASSERTS COMPUTED STYLE RATHER THAN THE MEDIA QUERY. A test that
 * greps `index.css` for the `@media` block only re-states the CSS in a
 * second place; it would still pass if the rule stopped *applying* (wrong
 * selector, overridden by a later import, scoped into a layer that loses).
 * Reading `getComputedStyle` through a real browser under a real
 * `prefers-reduced-motion` signal is the only form that can fail for the
 * right reason. Playwright's `reducedMotion` context option emits the
 * genuine CDP signal, so this is the browser answering, not a stub.
 *
 * WHY `/teacher/schemes`. It is the one route that carries all three of the
 * rule's declarations at once: `.lm-screen` (`index.css:727`) puts a real
 * `lm-in` animation on the screen wrapper, and its "Upload your own"
 * `<Button>` carries `transition-colors` (`components/ui/button.tsx:16`).
 * Asserting only an animation would leave `transition-duration` — a third of
 * the rule — unproven.
 *
 * The locators here are CSS class selectors, deliberately against this
 * suite's accessible-name idiom. That is not a test-only hook: `.lm-screen`
 * is the product's own class and is precisely the subject under test. There
 * is no accessible name for "the element carrying the entry animation".
 *
 * VERIFY BY INVERSION when touching this file: delete the `index.css:742`
 * block and the two `reduce` expectations must fail. A reduced-motion test
 * that still passes with the rule removed is the "passes for the wrong
 * reason" shape this build has already paid for once (P5.5 chunk C).
 */

/** `getComputedStyle` returns CSS time strings ("0.32s", "0.001ms"). */
function millis(cssTime: string): number {
  const value = Number.parseFloat(cssTime)
  if (Number.isNaN(value)) throw new Error(`Not a CSS time: ${JSON.stringify(cssTime)}`)
  return cssTime.trim().endsWith("ms") ? value : value * 1000
}

async function gotoSchemes(page: Page): Promise<void> {
  const { teacher } = readSeed()
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })
  await page.goto("/teacher/schemes")
  await expect(page.getByRole("heading", { name: "Mark schemes" })).toBeVisible({
    timeout: 15_000,
  })
}

/**
 * The two durations the rule governs, read off the live page.
 *
 * `animation-duration` is reported from the *declaration*, not from how much
 * of the animation is left, so a finished `lm-in` still reports its declared
 * 0.32s — this does not race the animation.
 */
async function motionDurations(page: Page): Promise<{ animation: number; transition: number }> {
  const screen = page.locator(".lm-screen").first()
  await expect(screen).toBeVisible()
  const button = page.getByRole("button", { name: /upload your own/i })
  await expect(button).toBeVisible()

  const animation = await screen.evaluate(
    (el) => getComputedStyle(el).animationDuration,
  )
  const transition = await button.evaluate(
    (el) => getComputedStyle(el).transitionDuration,
  )
  return { animation: millis(animation), transition: millis(transition) }
}

test.describe("motion allowed (the default)", () => {
  test("the entry animation and the button transition really do animate", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await gotoSchemes(page)
    const { animation, transition } = await motionDurations(page)

    // The control half of the proof. Without it, the `reduce` test below
    // could pass on a page where nothing was ever animated in the first
    // place — a vacuous pass that looks identical to a real one.
    expect(animation, ".lm-screen should carry a real entry animation").toBeGreaterThan(1)
    expect(transition, "the Button should carry a real colour transition").toBeGreaterThan(1)

    expect(errors, "console errors").toEqual([])
  })

  /*
   * The loading tiers stage on `animation-delay` with a `0s` duration and a
   * `both` fill, so the backwards fill holds `visibility: hidden` until the
   * delay elapses: the delay IS the gate. The global rule above zeroes every
   * delay, so it carries an explicit carve-out for these two
   * (`index.css`, the `@media (prefers-reduced-motion: reduce)` block).
   *
   * Without that carve-out, tier 3's "Still loading, reload the page" sits in
   * `RouteFallback`'s `role="status"` from the first frame of every
   * navigation — announced, and reachable by Tab, for a page that is not
   * stuck. That shipped once and was caught in review, while a unit test
   * pinning the token VALUES stayed green throughout.
   *
   * `loadingTiers.test.ts` now pins the carve-out's text, which catches
   * someone deleting it. This asserts the BEHAVIOUR, which additionally
   * catches the variants that leave the carve-out present and green: a
   * `visibility` declaration added to the blanket rule, a change to
   * `lm-appear`'s explicit `from`, or the `both` fill being dropped.
   */
  test("the staging tiers still stage, because their delay is a timer not motion", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await page.emulateMedia({ reducedMotion: "reduce" })
    await gotoSchemes(page)

    const staged = await page.evaluate(() => {
      const probe = (className: string) => {
        const el = document.createElement("div")
        el.className = className
        document.body.appendChild(el)
        const { visibility, animationDelay } = getComputedStyle(el)
        el.remove()
        return { visibility, animationDelay }
      }
      return { skeleton: probe("lm-tier-skeleton"), slow: probe("lm-tier-slow") }
    })

    // Hidden on the first frame is the whole point: the tier has not elapsed.
    expect(staged.skeleton.visibility, "tier 2 must not paint before its delay").toBe("hidden")
    expect(staged.slow.visibility, "tier 3 must not paint before its delay").toBe("hidden")

    // And the delays survive as real times rather than collapsing with the
    // rest, which is what keeps the `both` fill's window open at all.
    expect(parseFloat(staged.skeleton.animationDelay)).toBeGreaterThan(0.1)
    expect(parseFloat(staged.slow.animationDelay)).toBeGreaterThan(1)

    expect(errors, "console errors").toEqual([])
  })
})

test.describe("prefers-reduced-motion: reduce", () => {
  test("the global rule zeroes both the animation and the transition", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    // `page.emulateMedia`, NOT `test.use({ reducedMotion })`. Both emit the
    // same real CDP signal, but `reducedMotion` is not a declared key of
    // `PlaywrightTestOptions` in the pinned Playwright (1.62.1 — `colorScheme`
    // is there, `reducedMotion` is not), so the `test.use` form is a type
    // error. It would never be caught: `web/e2e/` is in no tsconfig `include`
    // (D3.20), so nothing typechecks this directory. `emulateMedia` is a
    // fully-typed Page API, which keeps the correctness of this file
    // independent of that carried gap.
    await page.emulateMedia({ reducedMotion: "reduce" })
    await gotoSchemes(page)
    const { animation, transition } = await motionDurations(page)

    // 0.001ms, not 0: the rule neutralises duration without setting
    // `animation: none`, which is deliberate — an infinite ambient animation
    // (`lm-pulse`) collapses to one instant cycle rather than freezing
    // mid-frame. Assert "effectively instant", not an exact literal.
    expect(animation, "the entry animation should be effectively instant").toBeLessThan(1)
    expect(transition, "the button transition should be effectively instant").toBeLessThan(1)

    expect(errors, "console errors").toEqual([])
  })

  /*
   * The loading tiers stage on `animation-delay` with a `0s` duration and a
   * `both` fill, so the backwards fill holds `visibility: hidden` until the
   * delay elapses: the delay IS the gate. The global rule above zeroes every
   * delay, so it carries an explicit carve-out for these two
   * (`index.css`, the `@media (prefers-reduced-motion: reduce)` block).
   *
   * Without that carve-out, tier 3's "Still loading, reload the page" sits in
   * `RouteFallback`'s `role="status"` from the first frame of every
   * navigation — announced, and reachable by Tab, for a page that is not
   * stuck. That shipped once and was caught in review, while a unit test
   * pinning the token VALUES stayed green throughout.
   *
   * `loadingTiers.test.ts` now pins the carve-out's text, which catches
   * someone deleting it. This asserts the BEHAVIOUR, which additionally
   * catches the variants that leave the carve-out present and green: a
   * `visibility` declaration added to the blanket rule, a change to
   * `lm-appear`'s explicit `from`, or the `both` fill being dropped.
   */
  test("the staging tiers still stage, because their delay is a timer not motion", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await page.emulateMedia({ reducedMotion: "reduce" })
    await gotoSchemes(page)

    const staged = await page.evaluate(() => {
      const probe = (className: string) => {
        const el = document.createElement("div")
        el.className = className
        document.body.appendChild(el)
        const { visibility, animationDelay } = getComputedStyle(el)
        el.remove()
        return { visibility, animationDelay }
      }
      return { skeleton: probe("lm-tier-skeleton"), slow: probe("lm-tier-slow") }
    })

    // Hidden on the first frame is the whole point: the tier has not elapsed.
    expect(staged.skeleton.visibility, "tier 2 must not paint before its delay").toBe("hidden")
    expect(staged.slow.visibility, "tier 3 must not paint before its delay").toBe("hidden")

    // And the delays survive as real times rather than collapsing with the
    // rest, which is what keeps the `both` fill's window open at all.
    expect(parseFloat(staged.skeleton.animationDelay)).toBeGreaterThan(0.1)
    expect(parseFloat(staged.slow.animationDelay)).toBeGreaterThan(1)

    expect(errors, "console errors").toEqual([])
  })
})
