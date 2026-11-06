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
  ...[900, 1100, 1247, 1248, 1300].map((width) => ({
    // One breakpoint decides both: exactly one of {sidebar column, menu button}
    // is visible at any width above the phone range. Both follow `shell-lg`
    // (1248px): the drawer and its menu button below it, the column from it.
    id: `teacher-sidebar-xor-menu-${width}`,
    width,
    app: TEACHER_HOME,
    async run(page) {
      const menu = await page.getByRole("button", { name: "Open teacher navigation" }).isVisible()
      const sidebar = await page.getByRole("navigation", { name: "Teacher", exact: true }).isVisible()
      if (menu === sidebar) throw new Error(`at ${width}px: menu button visible=${menu}, sidebar visible=${sidebar}; exactly one must show`)
      const columnExpected = width >= 1248
      if (sidebar !== columnExpected) {
        throw new Error(`at ${width}px: sidebar column visible=${sidebar}, expected ${columnExpected} (drawer below 1248px)`)
      }
    },
  })),
]

async function openNavFromMore(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  await more.click()
  const dialog = page.getByRole("dialog")
  await dialog.waitFor()
  return { more, dialog }
}

SHELL_CHECKS.push(
  {
    id: "teacher-drawer-traps-focus-and-escape-returns",
    width: 768,
    app: TEACHER_HOME,
    async run(page) {
      const { more, dialog } = await openNavFromMore(page)
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab")
        const inside = await dialog.evaluate((el) => el.contains(document.activeElement))
        if (!inside) throw new Error(`drawer: focus left the dialog after ${i + 1} Tab presses`)
      }
      await page.keyboard.press("Shift+Tab")
      if (!(await dialog.evaluate((el) => el.contains(document.activeElement)))) throw new Error("drawer: Shift+Tab escaped")
      await page.keyboard.press("Escape")
      await assertHidden(dialog, "drawer")
      await assertFocused(more, "More tab")
    },
  },
  {
    id: "teacher-drawer-has-one-labelled-nav",
    width: 768,
    app: TEACHER_HOME,
    async run(page) {
      const { dialog } = await openNavFromMore(page)
      const navs = await dialog.locator("nav[aria-label]").count()
      if (navs !== 1) throw new Error(`drawer: expected 1 labelled nav, found ${navs}`)
      await page.getByRole("button", { name: "Close menu" }).click()
      await assertHidden(dialog, "drawer via Close menu")
    },
  },
  {
    id: "teacher-rail-is-one-labelled-nav",
    width: 1440,
    app: TEACHER_HOME,
    async run(page) {
      const navs = await page.locator('nav[aria-label="Teacher"]').count()
      if (navs !== 1) throw new Error(`rail: expected 1 nav labelled Teacher, found ${navs}`)
    },
  },
)
