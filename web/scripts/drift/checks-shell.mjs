/*
 * Browser behaviour the Node-only unit runner cannot see (vitest.config.ts,
 * D3.20): focus return, Escape, focus trap, keyboard on the subject tree and
 * settings by URL. Each check opens the real app (mocked API, harness.mjs)
 * and throws on the first broken expectation. Later tasks append checks.
 */
import { PNG } from "pngjs"
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
/** Focus lands in the dialog a frame after it mounts; poll rather than assume. */
export async function assertFocusWithin(locator, label) {
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      if (await locator.evaluate((el) => el.contains(document.activeElement), undefined, { timeout: 500 })) return
    } catch {
      throw new Error(`${label}: the element is gone or unreachable, expected focus within it`)
    }
    await locator.page().waitForTimeout(50)
  }
  throw new Error(`${label}: focus never moved into the dialog`)
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
  await assertFocusWithin(dialog, "drawer")
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
    id: "teacher-drawer-menu-button-escape-returns-focus-1100",
    width: 1100,
    app: TEACHER_HOME,
    async run(page) {
      const menu = page.getByRole("button", { name: "Open teacher navigation" })
      await menu.click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      await assertFocusWithin(dialog, "drawer opened from the menu button")
      await page.keyboard.press("Escape")
      await assertHidden(dialog, "drawer opened from the menu button")
      await assertFocused(menu, "menu button")
    },
  },
  {
    // Deterministic: open and press Escape in one task, so the keydown fires
    // before the requestAnimationFrame that moves focus into the panel (focus
    // is still on the menu button and the event never targets the panel).
    id: "teacher-drawer-escape-before-focus-moves-1100",
    width: 1100,
    app: TEACHER_HOME,
    async run(page) {
      const menu = page.getByRole("button", { name: "Open teacher navigation" })
      const stillOnTrigger = await menu.evaluate(
        (el) =>
          new Promise((resolve) => {
            // Registered before the click, so it runs ahead of the drawer's own focus frame
            // (rAF callbacks run in registration order) yet after React has committed.
            requestAnimationFrame(() => {
              const onTrigger = document.activeElement === el
              document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
              resolve(onTrigger)
            })
            el.focus()
            el.click()
          }),
      )
      if (!stillOnTrigger) throw new Error("test setup: focus had already moved into the drawer, the race was not exercised")
      await assertHidden(page.getByRole("dialog"), "drawer closed by an Escape before focus moved in")
      await assertFocused(menu, "menu button")
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

/** Mean luma (0..255) of a PNG screenshot. */
function meanLuma(buffer) {
  const { data } = PNG.sync.read(buffer)
  let sum = 0
  for (let i = 0; i < data.length; i += 4) sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]
  return sum / (data.length / 4)
}

/** Alpha of a computed colour: "rgba(r, g, b, a)", "oklch(l c h / a)", "color(srgb r g b / a)"; 1 when opaque. */
function alphaOf(color) {
  const slash = color.match(/\/\s*([\d.]+)(%?)\s*\)$/)
  if (slash) return slash[2] ? Number(slash[1]) / 100 : Number(slash[1])
  const rgba = color.match(/^rgba\([^)]*,\s*([\d.]+)\)$/)
  return rgba ? Number(rgba[1]) : 1
}

/**
 * Task 4a: the floating bar is 86% opaque over a backdrop blur. The bar is
 * scrolled into its stuck state, then the same clip of it is shot twice:
 * once over the plain page and once with a contrasting block fixed under it.
 * The block must show through faintly: the mean luma moves, but by much less
 * than a clear bar would let it.
 */
export function barIsTranslucent(id, app, theme) {
  return {
    id,
    width: 1440,
    theme,
    app,
    async run(page) {
      const bar = page.locator("header[data-stuck]").first()
      const style = await bar.evaluate((el) => {
        const s = getComputedStyle(el)
        return { bg: s.backgroundColor, blur: s.backdropFilter || s.webkitBackdropFilter || "" }
      })
      if (!/blur\(/.test(style.blur)) throw new Error(`${theme}: bar backdrop-filter is "${style.blur}", expected a blur`)
      const alpha = alphaOf(style.bg)
      if (!(alpha > 0.8 && alpha < 0.9)) throw new Error(`${theme}: bar background ${style.bg} has alpha ${alpha}, expected 0.86`)
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px"
        window.scrollTo(0, 400)
      })
      await page.waitForFunction(() => document.querySelector("header[data-stuck]")?.getAttribute("data-stuck") === "true")
      const box = await bar.boundingBox()
      const clip = { x: box.x + 4, y: box.y + 4, width: box.width - 8, height: box.height - 8 }
      const plain = meanLuma(await page.screenshot({ clip, animations: "disabled" }))
      await page.evaluate(
        ([top, height, colour]) => {
          const probe = document.createElement("div")
          probe.style.cssText = `position:fixed;inset-inline:0;top:${top}px;height:${height}px;background:${colour};z-index:0;pointer-events:none`
          document.body.append(probe)
        },
        [box.y, box.height, theme === "dark" ? "#fff" : "#000"],
      )
      const covered = meanLuma(await page.screenshot({ clip, animations: "disabled" }))
      const moved = Math.abs(plain - covered)
      if (moved < 4) throw new Error(`${theme}: content under the bar is not visible (luma ${plain.toFixed(1)} -> ${covered.toFixed(1)})`)
      if (moved > 80) throw new Error(`${theme}: the bar is too clear (luma ${plain.toFixed(1)} -> ${covered.toFixed(1)})`)
    },
  }
}

SHELL_CHECKS.push(
  barIsTranslucent("teacher-bar-translucent-light", TEACHER_HOME, "light"),
  barIsTranslucent("teacher-bar-translucent-dark", TEACHER_HOME, "dark"),
)
