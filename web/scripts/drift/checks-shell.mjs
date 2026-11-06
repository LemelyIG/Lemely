/*
 * Browser behaviour the Node-only unit runner cannot see (vitest.config.ts,
 * D3.20): focus return, Escape, focus trap, keyboard on the subject tree and
 * settings by URL. Each check opens the real app (mocked API, harness.mjs)
 * and throws on the first broken expectation. Later tasks append checks.
 */
import { teacherShellMocks } from "./mocks.mjs"

/** Radix hands focus back a frame after the panel unmounts, so poll briefly rather than read once. */
export async function assertFocused(locator, label) {
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      // Bounded so a re-mounted (detached) trigger fails fast with the label, not after 30 s.
      if (await locator.evaluate((el) => el === document.activeElement, undefined, { timeout: 500 })) return
    } catch {
      throw new Error(`${label}: the element is gone or unreachable, expected focus on it`)
    }
    await locator.page().waitForTimeout(50)
  }
  throw new Error(`${label}: expected focus on the element`)
}
export async function assertHidden(locator, label) {
  await locator.waitFor({ state: "hidden", timeout: 3000 }).catch(() => {
    throw new Error(`${label}: expected it to close`)
  })
}

const TEACHER_HOME = { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks }

export const SHELL_CHECKS = [
  {
    id: "teacher-bell-escape-returns-focus",
    app: TEACHER_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.click()
      await page.getByRole("menu").waitFor()
      await page.keyboard.press("Escape")
      await assertHidden(page.getByRole("menu"), "bell panel")
      await assertFocused(bell, "bell trigger")
    },
  },
  {
    id: "teacher-account-escape-returns-focus",
    app: TEACHER_HOME,
    async run(page) {
      const avatar = page.getByRole("button", { name: /^Your profile and account/ })
      await avatar.click()
      await page.getByRole("menu").waitFor()
      await page.keyboard.press("Escape")
      await assertHidden(page.getByRole("menu"), "account panel")
      await assertFocused(avatar, "avatar trigger")
    },
  },
  {
    id: "teacher-bell-keyboard-reachable",
    app: TEACHER_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.focus()
      await page.keyboard.press("Enter")
      await page.getByRole("menu").waitFor()
      await page.getByRole("menuitem").first().waitFor()
      // Keyboard open lands on a menu item; ArrowDown must move to a different one.
      const focusedItem = () =>
        page.evaluate(() => {
          const el = document.activeElement
          return el?.getAttribute("role") === "menuitem" ? (el.textContent ?? "").trim() : null
        })
      const opened = await focusedItem()
      if (!opened) throw new Error("bell menu: keyboard open did not focus a menu item")
      await page.keyboard.press("ArrowDown")
      await page.waitForTimeout(100)
      const next = await focusedItem()
      if (!next || next === opened) throw new Error(`bell menu: ArrowDown did not move focus to the next item (was "${opened}", now "${next}")`)
      await page.keyboard.press("Escape")
      await assertFocused(bell, "bell after keyboard open")
    },
  },
]
