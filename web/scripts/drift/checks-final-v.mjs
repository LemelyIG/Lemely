import { CLASS_DETAIL, NATIVE_HOME, NATIVE_TEACHER_HOME, QUIZ_ROWS, classPaper, jsonRoute, rosterApp, studentPracticeMocks } from "./checks-native.mjs"
import { teacherShellMocks } from "./mocks.mjs"

/*
 * NF final polish, lane F1 (visual). Behaviour checks for items 1, 4 and 5 of nf-final-polish-brief.md.
 * Items 2 and 3 are pinned by unit tests (tests/unit/finalPolishV.test.ts); item 6 lives in the
 * one-heading routes of checks-native.mjs.
 */

export const FINAL_V_CHECKS = []

const PLATFORMS = ["ios", "android"]
const openMore = async (page) => {
  await page.locator("nav.lm-native-tabbar button[aria-haspopup]").click()
  const dialog = page.getByRole("dialog", { name: "More" })
  await dialog.waitFor()
  await page.waitForTimeout(350)
  return dialog
}

/**
 * Narrow the title's container from its natural width down to 60px and ask, at every step, whether the
 * date span is ever split across two lines (an inline box that wraps reports one client rect per line).
 * Returns the widths at which it split.
 */
const widthsThatSplitTheDate = (scope, dateText) =>
  scope.evaluate((root, text) => {
    const span = [...root.querySelectorAll("span")].find((s) => s.textContent.trim() === text && !s.querySelector("span"))
    if (!span) return null
    const host = span.parentElement
    const natural = host.getBoundingClientRect().width
    const split = []
    for (let w = Math.floor(natural); w >= 60; w -= 4) {
      host.style.maxWidth = `${w}px`
      if (span.getClientRects().length > 1) split.push(w)
    }
    host.style.maxWidth = ""
    return split
  }, dateText)

FINAL_V_CHECKS.push(
  // 1. A date never breaks inside its token: the title wraps before it.
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-bell-row-date-never-splits`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.getByRole("button", { name: /^Notifications/ }).click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      await page.waitForTimeout(350)
      const split = await widthsThatSplitTheDate(dialog.locator(".lm-list-row").first(), "Thu 12 Nov")
      if (split === null) throw new Error("the bell row has no date span to check")
      if (split.length) throw new Error(`the date "Thu 12 Nov" splits across lines when the title is ${split.join(", ")}px wide`)
    },
  })),
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-notifications-page-date-never-splits`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/notifications" },
    async run(page) {
      await page.locator("main h2", { hasText: "Physics mock moved" }).waitFor()
      const split = await widthsThatSplitTheDate(page.locator("main h2", { hasText: "Physics mock moved" }), "Thu 12 Nov")
      if (split === null) throw new Error("the page title has no date span to check")
      if (split.length) throw new Error(`the date "Thu 12 Nov" splits across lines when the title is ${split.join(", ")}px wide`)
    },
  })),
  // 4. The native list view is a group named by TableOrList's `label`.
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-table-or-list-names-the-list`,
    platform,
    width: 390,
    app: { ...NATIVE_TEACHER_HOME, path: "/teacher/classes" },
    async run(page) {
      const group = page.getByRole("group", { name: "Your classes" })
      await group.waitFor({ timeout: 8000 }).catch(() => {
        throw new Error('the native list view has no group named "Your classes"')
      })
    },
  })),
)

/**
 * Native lists whose ListGroup already names itself (a section with a visible h2): the name is
 * announced once, from the heading. TableOrList must not add a group of the same name around it.
 */
const SELF_NAMED_LISTS = [
  {
    name: "Class roster",
    app: rosterApp,
  },
  {
    name: "Class papers",
    app: {
      ...NATIVE_TEACHER_HOME,
      path: "/teacher/classes/class-1/papers",
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/classes\/class-1(\?|$)/, (route) => jsonRoute(route, CLASS_DETAIL))
        await page.route(/\/api\/classes\/class-1\/papers(\?|$)/, (route) =>
          jsonRoute(route, { papers: [classPaper(1, "Amina Said", false), classPaper(2, "Omar Nabil", true)] }),
        )
      },
    },
  },
  {
    name: "Your quizzes",
    app: {
      ...NATIVE_TEACHER_HOME,
      path: "/teacher/quizzes",
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/teacher\/quizzes(\?|$)/, (route) => jsonRoute(route, { quizzes: QUIZ_ROWS }))
      },
    },
  },
]
FINAL_V_CHECKS.push(
  ...PLATFORMS.flatMap((platform) =>
    SELF_NAMED_LISTS.map(({ name, app }) => ({
      id: `fv-${platform}-self-named-list-is-named-once-${name.toLowerCase().replace(/ /g, "-")}`,
      platform,
      width: 390,
      app,
      async run(page) {
        await page.getByRole("heading", { name, exact: true }).waitFor({ timeout: 8000 })
        const heading = await page.getByRole("heading", { name, exact: true }).count()
        const group = await page.getByRole("group", { name, exact: true }).count()
        const region = await page.getByRole("region", { name, exact: true }).count()
        if (heading !== 1 || region !== 1 || group !== 0)
          throw new Error(`"${name}" is announced ${heading} heading, ${region} region, ${group} group; expected 1 heading, 1 region, 0 group`)
      },
    })),
  ),
)

/** Press on the first More row, drag down by `steps * 22` px, release, and click that row inside the swallow window. */
async function dragThenClick(page, steps, pauseMs = 12) {
  const dialog = await openMore(page)
  // A handle, not a locator: after a dismissal the row leaves the DOM and a locator would wait for it.
  const handle = await dialog.locator("a.lm-list-row").first().elementHandle()
  await handle.evaluate((a) => {
    window.__rowClicks = 0
    // The browser's own post-drag click lands on the capture target and would consume the sheet's swallow flag
    // before ours. Hold it back at the window so the one click that arrives is the one the check sends to the row.
    window.addEventListener("click", (e) => e.isTrusted && e.stopImmediatePropagation(), { capture: true })
    window.addEventListener("pointerup", () => (window.__upAt = performance.now()), { capture: true })
    a.addEventListener("click", (e) => {
      window.__rowClicks += 1
      e.preventDefault()
    })
  })
  const box = await handle.boundingBox()
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(x, y + i * 22)
    await page.waitForTimeout(pauseMs)
  }
  await page.mouse.up()
  // What a browser that did deliver the click after the drag would do: it lands on the row.
  const delay = await handle.evaluate((a) => { if (!a.isConnected) throw new Error("the row left the DOM before the click was sent (the check needs the exit animation)"); const d = performance.now() - window.__upAt; a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); return d })
  return { dialog, delay, clicks: await page.evaluate(() => window.__rowClicks) }
}

FINAL_V_CHECKS.push(
  // 5. The click after a row drag is suppressed, on a dismissal and on a snap-back.
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-row-drag-suppresses-the-click-on-dismiss`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, motion: true },
    async run(page) {
      const { clicks, delay } = await dragThenClick(page, 12)
      if (clicks !== 0) throw new Error(`the click after a dismissing row drag reached the row (${clicks}, ${Math.round(delay)}ms after pointerup)`)
    },
  })),
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-row-drag-suppresses-the-click-on-snap-back`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, motion: true },
    async run(page) {
      const { dialog, clicks, delay } = await dragThenClick(page, 2, 150)
      if (!(await dialog.isVisible())) throw new Error("a slow 44px drag dismissed the sheet; the snap-back case did not run")
      if (clicks !== 0) throw new Error(`the click after a snapping-back row drag reached the row (${clicks}, ${Math.round(delay)}ms after pointerup)`)
    },
  })),
  // 5. A downward drag on a row inside a scrolled inner list scrolls that list, not the sheet.
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-sheet-drag-from-a-scrolled-inner-list-does-not-move-the-sheet`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const point = await dialog.evaluate((el) => {
        const group = el.querySelector("[data-list-group]")
        for (let i = 0; i < 12; i++) group.appendChild(group.firstElementChild.cloneNode(true))
        const scroller = document.createElement("div")
        scroller.setAttribute("data-test-inner-scroller", "")
        scroller.style.cssText = "max-height:160px;overflow-y:auto"
        group.parentElement.insertBefore(scroller, group)
        scroller.appendChild(group)
        scroller.scrollTop = 80
        const row = group.querySelectorAll("a.lm-list-row")[2]
        const r = row.getBoundingClientRect()
        return { x: r.x + r.width / 2, y: r.y + r.height / 2, top: scroller.scrollTop, scrolls: scroller.scrollHeight > scroller.clientHeight }
      })
      if (!point.scrolls || point.top === 0) throw new Error(`the inner list does not scroll (${JSON.stringify(point)})`)
      await page.mouse.move(point.x, point.y)
      await page.mouse.down()
      let dragging = false
      for (let i = 1; i <= 10; i++) {
        await page.mouse.move(point.x, point.y + i * 12)
        await page.waitForTimeout(12)
        dragging ||= await dialog.evaluate((el) => el.hasAttribute("data-dragging"))
      }
      await page.mouse.up()
      if (dragging) throw new Error("the sheet followed a downward drag that began in a scrolled inner list")
      await page.waitForTimeout(300)
      if (!(await dialog.isVisible())) throw new Error("the sheet was dismissed by a drag inside a scrolled inner list")
    },
  })),
  // 5 (control). The same press with the inner list at its top still drags the sheet.
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-sheet-drag-from-an-inner-list-at-its-top-still-drags`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const point = await dialog.evaluate((el) => {
        const group = el.querySelector("[data-list-group]")
        for (let i = 0; i < 12; i++) group.appendChild(group.firstElementChild.cloneNode(true))
        const scroller = document.createElement("div")
        scroller.style.cssText = "max-height:160px;overflow-y:auto"
        group.parentElement.insertBefore(scroller, group)
        scroller.appendChild(group)
        const row = group.querySelectorAll("a.lm-list-row")[1]
        const r = row.getBoundingClientRect()
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
      })
      await page.mouse.move(point.x, point.y)
      await page.mouse.down()
      let dragging = false
      for (let i = 1; i <= 10; i++) {
        await page.mouse.move(point.x, point.y + i * 12)
        await page.waitForTimeout(12)
        dragging ||= await dialog.evaluate((el) => el.hasAttribute("data-dragging"))
      }
      await page.mouse.up()
      if (!dragging) throw new Error("an inner list at its top no longer lets a downward drag move the sheet")
    },
  })),
)

FINAL_V_CHECKS.push(
  // M3. Desktop's press does not animate `scale`: only the native frame adds it to the button's transition list.
  {
    id: "fv-other-button-transition-excludes-scale",
    width: 1280,
    app: { ...NATIVE_HOME, path: "/student/settings", motion: true },
    async run(page) {
      const r = await page.evaluate(() => {
        const b = document.querySelector("button.lm-btn.lm-press-scale:not(.lm-native-iconbtn)")
        if (!b) return null
        return { platform: document.documentElement.dataset.platform, props: getComputedStyle(b).transitionProperty }
      })
      if (!r) throw new Error("no button.lm-press-scale on the page to measure")
      if (r.platform !== "other") throw new Error(`expected platform other, got ${r.platform}`)
      const BASE = "color, background-color, border-color, transform"
      if (r.props !== BASE) throw new Error(`desktop button transition is "${r.props}", base is "${BASE}"`)
      const icon = await page.evaluate(() => {
        const b = document.querySelector("button.lm-native-iconbtn")
        return b ? getComputedStyle(b).transitionProperty : null
      })
      if (icon === null) throw new Error("no shell icon button (.lm-native-iconbtn) on the page to measure")
      if (/\bscale\b/.test(icon) || !/^color, /.test(icon)) throw new Error(`desktop shell icon button transition is "${icon}", base is transition-colors`)
    },
  },
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-shell-icon-button-keeps-scale`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/settings", motion: true },
    async run(page) {
      const props = await page.evaluate(() => {
        const b = document.querySelector("button.lm-native-iconbtn")
        return b ? getComputedStyle(b).transitionProperty : null
      })
      if (props === null) throw new Error("no shell icon button on the page to measure")
      if (!/\bscale\b/.test(props)) throw new Error(`the native shell icon button lost its scale transition: ${props}`)
    },
  })),
  ...PLATFORMS.map((platform) => ({
    id: `fv-${platform}-button-transition-keeps-scale`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/settings", motion: true },
    async run(page) {
      const props = await page.evaluate(() => {
        const b = document.querySelector("button.lm-btn.lm-press-scale:not(.lm-native-iconbtn)")
        return b ? getComputedStyle(b).transitionProperty : null
      })
      if (props === null) throw new Error("no button.lm-press-scale on the page to measure")
      if (!/\bscale\b/.test(props)) throw new Error(`the native press lost its scale transition: ${props}`)
    },
  })),
)

/* One batched capture of the touched screens (390px, both platforms, both themes). Off unless FV_CAPTURE_DIR is set. */
if (process.env.FV_CAPTURE_DIR) {
  const dir = process.env.FV_CAPTURE_DIR
  const SCREENS = [
    {
      name: "bell-sheet",
      app: NATIVE_HOME,
      async open(page) {
        await page.getByRole("button", { name: /^Notifications/ }).click()
        await page.getByRole("dialog", { name: "Notifications" }).waitFor()
      },
    },
    { name: "notifications-page", app: { ...NATIVE_HOME, path: "/student/notifications" }, async open(page) { await page.locator("main h2").first().waitFor() } },
    {
      name: "more-sheet",
      app: NATIVE_TEACHER_HOME,
      async open(page) {
        await openMore(page)
      },
    },
    { name: "teacher-classes-list", app: { ...NATIVE_TEACHER_HOME, path: "/teacher/classes" }, async open(page) { await page.getByRole("group", { name: "Your classes" }).waitFor({ timeout: 8000 }) } },
    { name: "practice-heading", app: { ...NATIVE_HOME, path: "/student/practice/0606", mocks: async (page) => { await NATIVE_HOME.mocks(page); await studentPracticeMocks(page) } }, async open(page) { await page.locator("main h1").first().waitFor() } },
  ]
  for (const platform of PLATFORMS)
    for (const theme of ["light", "dark"])
      for (const s of SCREENS)
        FINAL_V_CHECKS.push({
          id: `fvcap-${platform}-${theme}-${s.name}`,
          platform,
          theme,
          width: 390,
          app: { ...s.app, motion: true },
          async run(page) {
            await s.open(page)
            await page.waitForTimeout(500)
            await page.screenshot({ path: `${dir}/${platform}-${theme}-${s.name}.png` })
          },
        })
}
