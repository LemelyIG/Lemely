import { test, expect } from "@playwright/test"
import { signInAs, waitForRouteReady } from "./native-feel.helpers"
import { readSeed } from "./seed"

/*
 * Task 13 (C5b): the Appearance setting, end to end.
 *
 * WHAT EACH CASE PROVES, AND WHY IT CANNOT BE A UNIT TEST.
 *
 * (a) proves the flash-free pre-mount mechanism actually works in a real
 * browser: `public/shell-init.js` resolves and paints the theme before the
 * shell markup is even parsed (see that file's own comment), so a cold load
 * under dark OS emulation with no stored preference must already be
 * `data-theme="dark"` at `domcontentloaded` — before React has had any
 * chance to mount and apply anything itself. A unit test can assert the
 * script's source text says the right thing (`themeInit.test.ts` does); only
 * a real page load proves it actually runs at the right moment.
 *
 * (b)/(c) prove `useTheme`'s two live-update paths: an explicit choice
 * persists (survives a reload) and beats the OS, while "System" keeps
 * tracking the OS signal with no reload in between. Both need a real
 * `matchMedia` and a real `localStorage`, neither of which the unit runner
 * has (`vitest.config.ts`: `environment: "node"`, no jsdom).
 */

test.describe("theme: no-flash pre-mount init", () => {
  test("no stored preference under dark OS emulation: data-theme is already dark at domcontentloaded, and the meta's content matches its own dark hex", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" })
    await page.goto("/login", { waitUntil: "domcontentloaded" })

    const theme = await page.evaluate(() => document.documentElement.dataset.theme)
    expect(theme).toBe("dark")

    const meta = await page.evaluate(() => {
      const el = document.querySelector('meta[name="theme-color"]')
      return {
        content: el?.getAttribute("content") ?? null,
        dark: el?.getAttribute("data-theme-dark") ?? null,
        light: el?.getAttribute("data-theme-light") ?? null,
      }
    })
    expect(meta.content).not.toBeNull()
    expect(meta.content).toBe(meta.dark)
    expect(meta.content).not.toBe(meta.light)
  })

  test("no stored preference under light OS emulation: data-theme is light at domcontentloaded", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "light" })
    await page.goto("/login", { waitUntil: "domcontentloaded" })

    const theme = await page.evaluate(() => document.documentElement.dataset.theme)
    expect(theme).toBe("light")
  })
})

test.describe("theme: Appearance setting", () => {
  test("choosing Light persists, applies immediately, and wins over dark OS emulation after reload", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" })
    await signInAs(page, "student")
    await page.goto("/student/settings")
    await waitForRouteReady(page)

    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")

    await page.getByRole("radio", { name: "Light" }).check()
    // Applies immediately, no reload.
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light")

    await page.reload({ waitUntil: "domcontentloaded" })
    // Still dark-emulated at the OS level, but the explicit choice wins.
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light")

    const storedTheme = await page.evaluate(() => localStorage.getItem("lemely.theme"))
    expect(storedTheme).toBe("light")
  })

  test("System follows the OS live, with no reload, once selected", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" })
    await signInAs(page, "student")
    await page.goto("/student/settings")
    await waitForRouteReady(page)

    await page.getByRole("radio", { name: "System" }).check()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light")

    await page.emulateMedia({ colorScheme: "dark" })
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")

    await page.emulateMedia({ colorScheme: "light" })
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light")
  })

  // Task 14 (C5c): `nivoTheme.ts` now re-resolves its palette on a
  // `data-theme` change (a `MutationObserver` on `document.documentElement`
  // — see that file's `useNivoTheme`), so a chart under dark OS emulation
  // must actually be drawn in the dark ladder's `--ink-muted`, not whatever
  // was resolved at the light-mode mount that happened before this test's
  // `emulateMedia` ever ran.
  //
  // ClassAnalytics (T-04) is the chart-heaviest screen in the product — the
  // grade-distribution bar chart's category axis prints a tick per grade
  // band, and `buildNivoTheme` (nivoTheme.ts) sets every tick's `fill` to
  // `--ink-muted`. Comparing raw strings would be fragile (the token is
  // authored as `oklch(...)`, a resolved SVG `fill` is reported back through
  // `getComputedStyle` in whatever colour-function form the browser chooses
  // to serialise it in), so both sides of the comparison go through
  // `getComputedStyle` in the SAME page, on the SAME browser, so they land in
  // the same serialised form regardless of what that form is.
  test("chart text fill matches resolved --ink-muted in dark", async ({ page }) => {
    const seed = readSeed()
    await page.emulateMedia({ colorScheme: "dark" })
    await signInAs(page, "teacher")
    await page.goto(`/teacher/classes/${seed.class.classId}/analytics`)
    await waitForRouteReady(page)
    await expect(page.getByText("Topic weakness heatmap")).toBeVisible({ timeout: 15_000 })
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")

    // The dark ladder's --ink-muted, resolved the same way any other
    // CSS-property comparison in this file is: through the browser's own
    // computed style, not a raw custom-property string.
    const expectedFill = await page.evaluate(() => {
      const probe = document.createElement("div")
      probe.style.color = "var(--ink-muted)"
      document.body.appendChild(probe)
      const value = getComputedStyle(probe).color
      probe.remove()
      return value
    })

    // The grade-distribution chart's category axis (Grade distribution ->
    // BarChart -> axis.ticks.text, all fill: --ink-muted) — the first `<text>`
    // Nivo renders on the page.
    const tickText = page.locator("svg text").first()
    await expect(tickText).toBeVisible()
    const actualFill = await tickText.evaluate((el) => getComputedStyle(el).fill)

    expect(actualFill).toBe(expectedFill)
  })
})
