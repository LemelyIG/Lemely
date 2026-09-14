import { test, expect } from "@playwright/test"
import { signInAs, waitForRouteReady } from "./native-feel.helpers"

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

  // Task 14 (C5c) makes this assertion meaningful, once nivoTheme.ts
  // re-resolves its palette on a data-theme change (a MutationObserver on
  // document.documentElement). This is a named placeholder only — do not
  // implement it here; Task 14 removes the fixme. No other fixme/skip may
  // survive this file (Task 15 asserts that).
  test.fixme("chart text fill matches resolved --ink-muted in dark", async () => {})
})
