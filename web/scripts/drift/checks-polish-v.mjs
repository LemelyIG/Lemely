import { NATIVE_HOME, NATIVE_SUBJECT, NATIVE_TEACHER_HOME, reviewApp } from "./checks-native.mjs"
import { teacherShellMocks } from "./mocks.mjs"

/*
 * NF polish batch, lane P1 (visual). Behaviour checks for items 1-14 and 24 of nf-polish-brief.md.
 * Kept in its own file so the lane that edits checks-native.mjs for items 16-23 merges cleanly.
 */

export const POLISH_V_CHECKS = []

const PLATFORMS = ["ios", "android"]
const openMore = async (page) => {
  await page.locator("nav.lm-native-tabbar button[aria-haspopup]").click()
  const dialog = page.getByRole("dialog", { name: "More" })
  await dialog.waitFor()
  await page.waitForTimeout(350)
  return dialog
}
const longPressFirstCard = async (page) => {
  const card = page.locator("main h2").first().locator("xpath=ancestor::div[@tabindex='-1'][1]")
  await card.waitFor()
  const box = await card.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + 8)
  await page.mouse.down()
  await page.waitForTimeout(700)
  await page.mouse.up()
  const dialog = page.getByRole("dialog")
  await dialog.waitFor()
  await page.waitForTimeout(350)
  return dialog
}
const NOTIFICATIONS_APP = { ...NATIVE_HOME, path: "/student/notifications" }
const NOTIFICATIONS_APP_MOTION = { ...NOTIFICATIONS_APP, motion: true }
/** Resolve a CSS colour token to the computed colour a property would paint. */
const tokenColour = (page, token) =>
  page.evaluate((t) => {
    const probe = document.createElement("i")
    probe.style.backgroundColor = `var(${t})`
    document.body.appendChild(probe)
    const c = getComputedStyle(probe).backgroundColor
    probe.remove()
    return c
  }, token)

POLISH_V_CHECKS.push(
  // 1. Eyebrows above a heading are gone on the native frame and stay on desktop.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-no-eyebrow-above-a-heading`,
    platform,
    width: 390,
    app: NOTIFICATIONS_APP,
    async run(page) {
      await page.locator("main h1").waitFor({ state: "attached" })
      const shown = await page.evaluate(() =>
        [...document.querySelectorAll("main .font-mono.uppercase, main .text-eyebrow")]
          .filter((e) => e.checkVisibility() && /^inbox$/i.test(e.textContent.trim()))
          .map((e) => e.textContent.trim()),
      )
      if (shown.length) throw new Error(`an eyebrow still shows above the Notifications heading: ${shown}`)
    },
  })),
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-teacher-hero-has-no-eyebrow`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      await page.getByRole("heading", { name: "Mark your first papers" }).waitFor()
      const shown = await page.evaluate(() =>
        [...document.querySelectorAll("p, div")].filter((e) => e.checkVisibility() && e.textContent.trim() === "Every mark, explained.").length,
      )
      if (shown) throw new Error("the teacher hero still shows its eyebrow")
    },
  })),
  {
    id: "pv-other-desktop-keeps-the-eyebrow",
    width: 1440,
    app: NOTIFICATIONS_APP,
    async run(page) {
      await page.locator("main h1").waitFor()
      const shown = await page.evaluate(() =>
        [...document.querySelectorAll("main .font-mono.uppercase")].some((e) => e.checkVisibility() && /^inbox$/i.test(e.textContent.trim())),
      )
      if (!shown) throw new Error("desktop lost the Inbox eyebrow")
    },
  },
  // 2. An own-text page heading is 24px on the native frame.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-own-text-h1-is-24px`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const h = page.locator('main h1[data-page-heading="own"]').first()
      await h.waitFor()
      const size = await h.evaluate((el) => getComputedStyle(el).fontSize)
      if (size !== "24px") throw new Error(`own-text h1 is ${size}, expected 24px`)
    },
  })),
  // 3. The More sheet.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-more-sheet-header-and-current-page`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/friends" },
    async run(page) {
      const dialog = await openMore(page)
      const m = await dialog.evaluate((el) => {
        const grabber = el.querySelector(".lm-sheet-grabber").getBoundingClientRect()
        const title = el.querySelector(".lm-native-sheet-title").getBoundingClientRect()
        const list = el.querySelector("[data-list-group]").getBoundingClientRect()
        const closes = [...el.querySelectorAll('[data-slot="sheet-close"]')].filter((b) => b.checkVisibility())
        const current = [...el.querySelectorAll('a[aria-current="page"]')].map((a) => a.textContent.trim())
        const rows = [...el.querySelectorAll("a.lm-list-row")]
        const dividers = rows.slice(1).map((r) => getComputedStyle(r).borderTopWidth)
        const ts = getComputedStyle(el.querySelector(".lm-native-sheet-title"))
        // The title's own padding is spacing, not text: measure from the glyph box.
        return { gapTop: title.top + parseFloat(ts.paddingTop) - grabber.bottom, gapBelow: list.top - (title.bottom - parseFloat(ts.paddingBottom)), closes: closes.length, current, dividers }
      })
      const maxTop = platform === "android" ? 24 : 12 // the M3 handle keeps its own 22dp below it
      if (m.gapTop > maxTop) throw new Error(`the title sits ${m.gapTop}px under the grabber, expected at most ${maxTop}`)
      if (m.gapBelow < 12) throw new Error(`the list starts ${m.gapBelow}px under the title, expected at least 12`)
      if (m.current.join() !== "Friends") throw new Error(`the current page is marked on [${m.current}], expected Friends`)
      if (platform === "ios" && m.closes !== 1) throw new Error(`iOS More has ${m.closes} close controls, expected 1`)
      if (platform === "android" && m.closes !== 0) throw new Error(`Android More has ${m.closes} visible close controls, expected 0`)
      const chevrons = await dialog.locator("[data-disclosure]").evaluateAll((els) => els.filter((e) => e.checkVisibility()).length)
      if (platform === "ios" && chevrons < 1) throw new Error("iOS More rows show no disclosure chevron")
      if (platform === "android" && chevrons !== 0) throw new Error("Android More rows show a chevron")
    },
  })),
  {
    id: "pv-android-more-rows-have-no-dividers",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/friends" },
    async run(page) {
      const dialog = await openMore(page)
      const dividers = await dialog.evaluate((el) => [...el.querySelectorAll("a.lm-list-row")].slice(1).map((r) => getComputedStyle(r).borderTopWidth))
      if (dividers.length < 2) throw new Error("the More list has too few rows to show a divider")
      if (dividers.some((d) => d !== "0px")) throw new Error(`Android More rows keep dividers ${dividers}`)
    },
  },
  {
    id: "pv-ios-more-close-control-closes-the-sheet",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const dialog = await openMore(page)
      await dialog.locator('[data-slot="sheet-close"]').click()
      await dialog.waitFor({ state: "detached" })
    },
  },
  {
    id: "pv-android-more-marks-the-current-row-in-a-pill",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/friends" },
    async run(page) {
      const dialog = await openMore(page)
      const want = await tokenColour(page, "--md-secondary-container")
      const r = await dialog.evaluate((el) => {
        const cur = getComputedStyle(el.querySelector('a[aria-current="page"]'))
        const other = getComputedStyle([...el.querySelectorAll("a.lm-list-row")].find((a) => !a.hasAttribute("aria-current")))
        return { bg: cur.backgroundColor, otherBg: other.backgroundColor }
      })
      if (r.bg !== want) throw new Error(`current row background ${r.bg}, expected secondary container ${want}`)
      if (r.otherBg === want) throw new Error("another row shares the current marker")
    },
  },
  // 4. FAB: animated extend and collapse, the shell does not own the scroll state, a still name.
  {
    id: "pv-android-fab-animates-extend-and-collapse",
    platform: "android",
    width: 390,
    app: { ...NATIVE_TEACHER_HOME, motion: true },
    async run(page) {
      const fab = page.locator(".lm-native-fab")
      const width = () => fab.evaluate((el) => el.getBoundingClientRect().width)
      const full = await width()
      if (full <= 56) throw new Error("the FAB is not extended at the top")
      const dur = await page.locator(".lm-native-fab-label").evaluate((el) => getComputedStyle(el).transitionDuration)
      if (!/^0\.2s/.test(dur)) throw new Error(`label transition lasts ${dur}, expected 0.2s`)
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px"
        window.scrollTo(0, 400)
      })
      // Sampled inside the 200ms: a step would only ever show the two end widths.
      const seen = new Set()
      for (let i = 0; i < 12; i++) {
        seen.add(Math.round(await width()))
        await page.waitForTimeout(16)
      }
      const mid = [...seen].filter((w) => w > 57 && w < full - 1)
      if (!mid.length) throw new Error(`the width stepped ${[...seen]} with no frame between 56 and ${Math.round(full)}`)
      await page.waitForFunction(() => document.querySelector(".lm-native-fab").getBoundingClientRect().width <= 56)
      const name = await page.getByRole("button", { name: "Create" }).count()
      if (name !== 1) throw new Error("a collapsed FAB lost its accessible name")
      const gap = await fab.evaluate((el) => el.getBoundingClientRect().width - 56)
      if (gap > 0.5) throw new Error(`the collapsed FAB is ${gap}px wider than 56`)
    },
  },
  {
    id: "pv-android-fab-is-instant-under-reduced-motion",
    platform: "android",
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const d = await page.locator(".lm-native-fab-label").evaluate((el) => getComputedStyle(el).transitionDuration)
      if (!/^0s/.test(d)) throw new Error(`reduced motion leaves a ${d} FAB transition`)
    },
  },
  // 5. Dark sheets separate from the dim: Sheet, Popover and Modal.
  ...PLATFORMS.flatMap((platform) =>
    [
      ["sheet", NATIVE_HOME, openMore],
      ["popover", NOTIFICATIONS_APP, longPressFirstCard],
      [
        "modal",
        reviewApp("?class_id=class-1&reason=low_confidence"),
        async (page) => {
          await page.locator("[data-review-filter]").click()
          const dialog = page.getByRole("dialog", { name: "Filter the review queue" })
          await dialog.waitFor()
          await page.waitForTimeout(350)
          return dialog
        },
      ],
    ].map(([kind, app, open]) => ({
      id: `pv-${platform}-dark-${kind}-sheet-lifts-off-the-dim`,
      platform,
      theme: "dark",
      width: 390,
      app,
      async run(page) {
        const dialog = await open(page)
        const low = await tokenColour(page, "--md-surface-container-low")
        const r = await dialog.evaluate((el) => {
          const s = getComputedStyle(el)
          return { bg: s.backgroundColor, shadow: s.boxShadow }
        })
        if (r.bg === low) throw new Error(`the dark ${kind} sheet is still container-low (${low}), the colour that sinks into the dim`)
        if (!/inset/.test(r.shadow)) throw new Error(`the dark ${kind} sheet has no top hairline (${r.shadow})`)
      },
    })),
  ),
  // 6 + 7. A single-row popover sheet: a short visible title names the dialog; tight to the grabber.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-popover-sheet-is-titled-and-tight`,
    platform,
    width: 390,
    app: NOTIFICATIONS_APP,
    async run(page) {
      const dialog = await longPressFirstCard(page)
      const r = await dialog.evaluate((el) => {
        const id = el.getAttribute("aria-labelledby")
        const t = id ? document.getElementById(id) : null
        const title = t?.getBoundingClientRect()
        const grabber = el.querySelector(".lm-sheet-grabber").getBoundingClientRect()
        const row = [...el.querySelectorAll("button")].find((b) => /mark read/i.test(b.textContent))?.getBoundingClientRect()
        const line = t ? parseFloat(getComputedStyle(t).lineHeight) : 0
        return {
          id,
          text: t?.textContent.trim() ?? null,
          visible: t ? t.checkVisibility() && getComputedStyle(t).position !== "absolute" : false,
          oneLine: title && line ? title.height - parseFloat(getComputedStyle(t).paddingBottom) - parseFloat(getComputedStyle(t).paddingTop) <= line + 1 : false,
          gapTop: title ? title.top + parseFloat(getComputedStyle(t).paddingTop) - grabber.bottom : null,
          gapRow: title && row ? row.top - (title.bottom - parseFloat(getComputedStyle(t).paddingBottom)) : null,
        }
      })
      if (r.text !== "Physics mock moved to Thu 12 Nov") throw new Error(`the sheet is named by "${r.text}" (${r.id}), expected the notification title`)
      if (!r.visible) throw new Error("the sheet's title is not visible")
      if (!r.oneLine) throw new Error("the sheet's title wraps to more than one line")
      if (r.gapTop > (platform === "android" ? 24 : 12)) throw new Error(`dead space: the title sits ${r.gapTop}px under the grabber`)
      if (r.gapRow > 16) throw new Error(`dead space: the row sits ${r.gapRow}px under the title`)
    },
  })),
  // 8. The popover sheet animates out like Modal: it stays mounted, marked closing, then goes.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-popover-sheet-exits-through-the-closing-phase`,
    platform,
    width: 390,
    app: NOTIFICATIONS_APP_MOTION,
    async run(page) {
      const dialog = await longPressFirstCard(page)
      await page.keyboard.press("Escape")
      const sawClosing = await page
        .waitForFunction(() => document.querySelector("[role=dialog][data-closing]") !== null, null, { timeout: 1500, polling: "raf" })
        .then(() => true, () => false)
      if (!sawClosing) throw new Error("the popover sheet unmounted without a closing phase")
      await dialog.waitFor({ state: "detached", timeout: 2000 })
    },
  })),
  // 9. iOS: the section label starts at the same x as the ledger's content.
  {
    id: "pv-ios-section-label-aligns-with-ledger-content",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const r = await page.evaluate(() => {
        const textLeft = (el) => {
          const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
          for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            if (!n.textContent.trim()) continue
            const range = document.createRange()
            range.selectNodeContents(n)
            return range.getBoundingClientRect().left
          }
          return null
        }
        const label = [...document.querySelectorAll("main *")].find((e) => e.children.length === 0 && /subjects this session/i.test(e.textContent))
        const row = document.querySelector("main a.lm-native-card-row")
        const chip = row?.querySelector("span.inline-flex")
        return { label: label ? textLeft(label) : null, row: chip ? chip.getBoundingClientRect().left : null }
      })
      if (r.label === null || r.row === null) throw new Error(`no label or ledger row (${JSON.stringify(r)})`)
      if (Math.abs(r.label - r.row) > 1) throw new Error(`the section label starts at x=${r.label}, the ledger content at x=${r.row}`)
    },
  },
  // 10 + 24. The view toggle matches Filter on Android; no `!` classes remain.
  {
    id: "pv-android-view-toggle-meets-the-48dp-floor-like-filter",
    platform: "android",
    width: 390,
    app: reviewApp(),
    async run(page) {
      const filter = page.locator("[data-review-filter]")
      await filter.waitFor()
      const toggle = page.getByRole("button", { name: "View table" })
      const [f, t] = await Promise.all([filter, toggle].map((l) => l.evaluate((el) => el.getBoundingClientRect().height)))
      if (t < 48) throw new Error(`View table is ${t}px high, expected at least 48`)
      if (f < 48) throw new Error(`Filter is ${f}px high, expected at least 48`)
    },
  },
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-button-floor-is-a-rule-not-an-important-utility`,
    platform,
    width: 390,
    app: reviewApp(),
    async run(page) {
      const b = page.locator("[data-review-filter]")
      await b.waitFor()
      const r = await b.evaluate((el) => ({ h: el.getBoundingClientRect().height, cls: el.className }))
      if (/!/.test(r.cls)) throw new Error(`a Button carries an important utility: ${r.cls}`)
      if (platform === "android" && r.h < 48) throw new Error(`an Android Button is ${r.h}px high, expected at least 48`)
      if (platform === "ios" && r.h > 47) throw new Error(`an iOS Button grew to ${r.h}px, expected the 44pt floor`)
    },
  })),
  // 11. The dark edge shadow is the scrim role, never raw black.
  {
    id: "pv-android-dark-edge-shadow-derives-from-the-scrim-role",
    platform: "android",
    theme: "dark",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const r = await page.evaluate(() => {
        const read = (name) => {
          const probe = document.createElement("i")
          probe.style.color = `var(${name})`
          document.body.appendChild(probe)
          const c = getComputedStyle(probe).color
          probe.remove()
          return c
        }
        return { edge: read("--native-edge-shadow"), scrim: read("--md-scrim") }
      })
      if (r.edge !== r.scrim) throw new Error(`dark edge shadow ${r.edge} is not the scrim role ${r.scrim}`)
    },
  },
  // 13. The Android card divider strip removes row dividers only.
  {
    id: "pv-android-card-strip-removes-row-dividers-only",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("main .lm-native-card").first().waitFor()
      const r = await page.evaluate(() => {
        const card = document.querySelector("main .lm-native-card:not([data-native-bleed='off'])")
        const mk = (tag, cls, parent) => {
          const el = document.createElement(tag)
          el.className = cls
          el.textContent = "x"
          parent.appendChild(el)
          return getComputedStyle(el).borderBottomWidth
        }
        const nested = document.createElement("div")
        card.appendChild(nested)
        return {
          directRow: mk("div", "border-b border-outline", card),
          input: mk("input", "border-b border-outline", nested),
          header: mk("th", "border-b border-outline", nested),
          divided: (() => {
            const d = document.createElement("div")
            d.className = "divide-y"
            card.appendChild(d)
            return mk("div", "border-b border-outline", d)
          })(),
        }
      })
      if (r.directRow !== "0px") throw new Error(`a direct row divider survived (${r.directRow})`)
      if (r.input === "0px") throw new Error("the strip removed an input's own border")
      if (r.header === "0px") throw new Error("the strip removed a table header's border")
    },
  },
  // 14. A drag that starts on a row dismisses the sheet and does not fire the row.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-sheet-dismisses-from-a-row-drag-without-a-click`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const before = new URL(page.url()).pathname
      const row = dialog.locator("a.lm-list-row").first()
      const box = await row.boundingBox()
      const x = box.x + box.width / 2
      await page.mouse.move(x, box.y + box.height / 2)
      await page.mouse.down()
      for (let i = 1; i <= 12; i++) {
        await page.mouse.move(x, box.y + box.height / 2 + i * 22)
        await page.waitForTimeout(12)
      }
      await page.mouse.up()
      await dialog.waitFor({ state: "detached", timeout: 3000 }).catch(() => {
        throw new Error("a drag that began on a row did not dismiss the sheet")
      })
      if (new URL(page.url()).pathname !== before) throw new Error(`the drag also tapped the row: ${page.url()}`)
    },
  })),
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-sheet-row-tap-still-navigates`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const row = dialog.locator("a.lm-list-row").first()
      const href = new URL(await row.evaluate((a) => a.href)).pathname
      await row.click()
      await dialog.waitFor({ state: "detached" })
      if (new URL(page.url()).pathname !== href) throw new Error(`a plain tap went to ${page.url()}, not ${href}`)
    },
  })),
  // 3. A long More list stays inside its detent and scrolls in the sheet body.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-more-sheet-with-many-rows-scrolls-inside-its-detent`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const dialog = await openMore(page)
      await dialog.evaluate((el) => {
        const group = el.querySelector("[data-list-group]")
        for (let i = 0; i < 24; i++) group.appendChild(group.firstElementChild.cloneNode(true))
      })
      await page.waitForTimeout(150)
      const r = await dialog.evaluate((el) => {
        const body = el.querySelector("[data-sheet-body]")
        const before = body.scrollTop
        body.scrollTop = 200
        return { top: el.getBoundingClientRect().top, innerH: innerHeight, scrolls: body.scrollHeight > body.clientHeight, moved: body.scrollTop > before }
      })
      if (r.top < 20) throw new Error(`the sheet reaches ${r.top}px from the top of the screen`)
      if (!r.scrolls || !r.moved) throw new Error(`a 25-row More list does not scroll inside the sheet (${JSON.stringify(r)})`)
    },
  })),
  // 15. A native push into a stored paper result gets one entrance: the push's slide, nothing replayed after it.
  ...PLATFORMS.map((platform) => ({
    id: `pv-${platform}-result-push-has-a-single-entrance`,
    platform,
    width: 390,
    app: {
      ...NATIVE_SUBJECT,
      motion: true,
      mocks: async (page) => {
        await NATIVE_SUBJECT.mocks(page)
        const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
        await page.route(/\/api\/student\/subject\/0606(\?|$)/, (route) =>
          json(route, {
            header: { name: "Add Maths", code: "0606", qualificationLevel: "IGCSE", intro: "x", forecast: "B", weightedMean: "62", weightedMeanDelta: "+4" },
            papersBreakdown: [],
            topicMap: [],
            paperHistory: [{ id: "paper-1", paper: "0606/12 \u00b7 Oct 2025", note: "Attempt 1", marks: "52/80", pct: "65%", grade: "B", gradeColor: "primary", tab: "history" }],
          }),
        )
        await page.route(/\/api\/student\/result\/paper-1/, (route) =>
          json(route, {
            code: "0606", paper: "Paper 12", session: "Oct 2025", markerLabel: "Marked by Lemely", headline: "52 out of 80, a grade B on this paper.",
            summary: "Method marks carried most of this paper.", awarded: 52, max: 80, pct: 65, grade: "B", boundaryYear: "2025", railLeft: 65,
            railFoot: "52/80", railNote: "Four marks below the A boundary.", theory: [], integrity: [], provenance: "0606_m25_qp_12.pdf",
          }),
        )
      },
    },
    async run(page) {
      const row = page.getByRole("button", { name: /0606\/12/ }).first()
      await row.waitFor()
      await page.evaluate(() => {
        window.__starts = []
        window.__opacity = []
        const seen = new WeakSet()
        const t0 = performance.now()
        const tick = () => {
          const t = Math.round(performance.now() - t0)
          for (const a of document.documentElement.getAnimations({ subtree: true })) {
            if (seen.has(a)) continue
            seen.add(a)
            window.__starts.push({ t, name: a.animationName ?? "", pseudo: a.effect?.pseudoElement ?? "", cls: a.effect?.target?.className?.toString() ?? "" })
          }
          const screen = document.querySelector("[data-screen]")
          if (screen) window.__opacity.push({ t, o: Number(getComputedStyle(screen).opacity) })
          requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      })
      await row.evaluate((el) => el.click())
      await page.getByText("52 out of 80").waitFor()
      await page.waitForTimeout(1200)
      const { starts, opacity } = await page.evaluate(() => ({ starts: window.__starts, opacity: window.__opacity }))
      const slide = starts.find((s) => /^lm-vt-(ios|axis)-new/.test(s.name))
      if (!slide) throw new Error(`no push slide started: ${JSON.stringify(starts)}`)
      // The screen is already at full opacity when the slide starts and stays there: no fade replays after the slide.
      const dips = opacity.filter((x) => x.t >= slide.t && x.o < 0.99)
      if (dips.length) throw new Error(`the screen fades again after the push began (min opacity ${Math.min(...dips.map((d) => d.o))} over ${dips.length} frames)`)
      const replays = starts.filter((s) => s.name === "lm-in" && /lm-screen/.test(s.cls) && s.t > slide.t + 150)
      if (replays.length) throw new Error(`a screen entrance restarted after the slide: ${JSON.stringify(replays)}`)
    },
  })),
  // 3. iOS: the inset group reads against the sheet surface, in both themes.
  ...["light", "dark"].map((theme) => ({
    id: `pv-ios-more-group-reads-against-the-sheet-${theme}`,
    platform: "ios",
    theme,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const r = await dialog.evaluate((el) => {
        // Colours come back in oklch; a 1x1 canvas turns any of them into sRGB.
        const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })
        const lum = (css) => {
          ctx.clearRect(0, 0, 1, 1)
          ctx.fillStyle = css
          ctx.fillRect(0, 0, 1, 1)
          const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
          return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        }
        const sheet = getComputedStyle(el).backgroundColor
        const group = getComputedStyle(el.querySelector("[data-list-group]")).backgroundColor
        return { sheet, group, delta: Math.abs(lum(sheet) - lum(group)) }
      })
      if (r.sheet === r.group) throw new Error(`the group and the sheet are the same colour (${r.sheet})`)
      if (r.delta < (theme === "dark" ? 0.025 : 0.04)) throw new Error(`the group barely separates from the sheet: ${r.group} on ${r.sheet} (luminance step ${r.delta.toFixed(3)})`)
    },
  })),
  // 1 (fix round 1). Eyebrows that carry data keep it on native, as a quiet line under the heading.
  ...PLATFORMS.flatMap((platform) =>
    [
      ["class-detail", "/teacher/classes/class-1", "Physics · 0625", "Year 11 Physics"],
      ["quiz-results", "/teacher/quizzes/quiz-1/assignments/asg-1/results", "0625 · Year 11 Physics", "Forces quiz"],
      ["quiz-builder", "/teacher/quizzes/quiz-1?step=3", "0625", "Forces quiz"],
    ].map(([name, path, meta, heading]) => ({
      id: `pv-${platform}-${name}-keeps-its-subject-as-a-quiet-line`,
      platform,
      width: 390,
      app: { ...NATIVE_TEACHER_HOME, path, mocks: dataEyebrowMocks },
      async run(page) {
        const h = page.locator("main h1", { hasText: heading })
        await h.waitFor()
        const r = await page.evaluate((text) => {
          const line = [...document.querySelectorAll("main [data-native-meta]")].find((e) => e.textContent.trim() === text)
          const eyebrow = [...document.querySelectorAll("main .text-eyebrow")].filter((e) => e.checkVisibility() && e.textContent.trim() === text)
          const h1 = document.querySelector("main h1")
          const lineBox = line?.getBoundingClientRect()
          return {
            shown: !!line && line.checkVisibility(),
            mono: line ? getComputedStyle(line).fontFamily.toLowerCase().includes("mono") : null,
            upper: line ? getComputedStyle(line).textTransform : null,
            below: lineBox && h1 ? lineBox.top >= h1.getBoundingClientRect().bottom - 1 || h1.getBoundingClientRect().height < 2 || getComputedStyle(h1).position === "absolute" : false,
            eyebrows: eyebrow.length,
          }
        }, meta)
        if (!r.shown) throw new Error(`the subject "${meta}" is not shown on native`)
        if (!r.below) throw new Error("the subject line sits above the heading, not under it")
        if (r.mono || r.upper === "uppercase") throw new Error("the subject is still styled as a mono eyebrow")
        if (r.eyebrows) throw new Error("the eyebrow itself still shows above the heading")
      },
    })),
  ),
  {
    id: "pv-other-1280-class-detail-keeps-the-eyebrow-and-no-meta-line",
    width: 1280,
    app: { ...NATIVE_TEACHER_HOME, path: "/teacher/classes/class-1", mocks: dataEyebrowMocks },
    async run(page) {
      await page.locator("main h1", { hasText: "Year 11 Physics" }).waitFor()
      const r = await page.evaluate(() => ({
        eyebrow: [...document.querySelectorAll("main .text-eyebrow")].some((e) => e.checkVisibility() && e.textContent.trim() === "Physics · 0625"),
        meta: [...document.querySelectorAll("main [data-native-meta]")].some((e) => e.checkVisibility()),
      }))
      if (!r.eyebrow) throw new Error("desktop lost the subject eyebrow")
      if (r.meta) throw new Error("desktop shows the native meta line")
    },
  },
  // 3 (fix round 1). The Android current pill keeps the row's glyph on the other rows' x; the iOS close centres on the title.
  {
    id: "pv-android-more-current-row-keeps-its-content-aligned",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/friends" },
    async run(page) {
      const dialog = await openMore(page)
      const xs = await dialog.evaluate((el) =>
        [...el.querySelectorAll("a.lm-list-row")].map((a) => ({ cur: a.hasAttribute("aria-current"), x: a.querySelector("svg").getBoundingClientRect().left })),
      )
      const cur = xs.find((x) => x.cur)
      const other = xs.find((x) => !x.cur)
      if (!cur || !other) throw new Error("no current and other row")
      if (Math.abs(cur.x - other.x) > 0.5) throw new Error(`the current row's glyph is at x=${cur.x}, the others at x=${other.x}`)
    },
  },
  {
    id: "pv-ios-more-close-is-centred-on-the-title",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const dialog = await openMore(page)
      const r = await dialog.evaluate((el) => {
        const t = el.querySelector(".lm-native-sheet-title")
        const range = document.createRange()
        range.selectNodeContents(t)
        const text = range.getBoundingClientRect()
        const c = el.querySelector('[data-slot="sheet-close"]').getBoundingClientRect()
        return { title: (text.top + text.bottom) / 2, close: (c.top + c.bottom) / 2 }
      })
      if (Math.abs(r.title - r.close) > 2) throw new Error(`the close control centre is at y=${r.close}, the title's at y=${r.title}`)
    },
  },
  // 15 (fix round 1). Desktop: a view-transition navigation plays one entrance, and none replays after it.
  {
    id: "pv-other-1280-view-transition-nav-replays-no-entrance",
    width: 1280,
    app: { ...NATIVE_HOME, motion: true },
    async run(page) {
      await page.locator("main").waitFor()
      await page.evaluate(() => {
        window.__starts = []
        window.__opacity = []
        const seen = new WeakSet()
        const t0 = performance.now()
        const tick = () => {
          const t = Math.round(performance.now() - t0)
          for (const a of document.documentElement.getAnimations({ subtree: true })) {
            if (seen.has(a)) continue
            seen.add(a)
            window.__starts.push({ t, name: a.animationName ?? "", pseudo: a.effect?.pseudoElement ?? "", cls: a.effect?.target?.className?.toString() ?? "" })
          }
          const screen = document.querySelector("[data-screen]")
          if (screen) window.__opacity.push({ t, o: Number(getComputedStyle(screen).opacity) })
          requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      })
      await page.locator('a[href="/student/classes"]:visible').first().click()
      await page.waitForURL("**/student/classes")
      await page.waitForTimeout(1000)
      const { starts, opacity } = await page.evaluate(() => ({ starts: window.__starts, opacity: window.__opacity }))
      const vt = starts.find((s) => /view-transition-new\(root\)/.test(s.pseudo))
      if (!vt) throw new Error(`no view transition ran: ${JSON.stringify(starts.map((s) => s.name))}`)
      const dips = opacity.filter((x) => x.t >= vt.t && x.o < 0.99)
      if (dips.length) throw new Error(`the screen fades again after the transition began (min opacity ${Math.min(...dips.map((d) => d.o))})`)
      const replays = starts.filter((s) => s.name === "lm-in" && /lm-screen/.test(s.cls) && s.t > vt.t + 150)
      if (replays.length) throw new Error(`an entrance restarted after the transition: ${JSON.stringify(replays)}`)
    },
  },
)

export async function dataEyebrowMocks(page) {
  await teacherShellMocks(page)
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
  await page.route(/\/api\/classes\/class-1(\?|$)/, (route) =>
    json(route, {
      id: "class-1", label: "Year 11 Physics", stats: [], mastery: [], distribution: [], students: [], subjectCode: "0625",
      subjectName: "Physics", schoolId: null, joinCode: null, atRiskCount: 0, lastActivityAt: null, topWeakness: null,
    }),
  )
  const quiz = { id: "quiz-1", subjectCode: "0625", title: "Forces quiz", status: "draft", targetGrade: "B", includedTopics: [], poolSource: null, requestedCount: null, timeLimitMinutes: null, builderStep: 3, questionCount: 0 }
  await page.route(/\/api\/teacher\/quizzes\/quiz-1(\?|$)/, (route) => json(route, { quiz, questions: [] }))
  await page.route(/\/api\/teacher\/quizzes\/pool-count/, (route) => json(route, { matching: 0, byBand: {}, shortfall: null, message: null }))
  await page.route(/\/api\/teacher\/quizzes\/quiz-1\/assignments\/asg-1\/results/, (route) =>
    json(route, {
      assignment: { id: "asg-1", classId: "class-1", className: "Year 11 Physics", assignedAt: "2026-11-01T09:00:00Z", dueAt: null, closesAt: null, rosterSize: 0, submissionCounts: {} },
      quizTitle: "Forces quiz", subjectCode: "0625", questionCount: 0, totalMarks: 0,
      completion: { rosterSize: 0, completedCount: 0, completionRate: null, statusCounts: {}, offRosterSubmissionCount: 0 },
      averagePercentage: null, medianPercentage: null, scoreDistribution: [], questionAnalysis: [], students: [], topicWeaknesses: [],
    }),
  )
}

// Fix round 2: the settings sheet's group gets the same iOS light grouped ground as More.
POLISH_V_CHECKS.push({
  id: "pv-ios-settings-group-matches-the-more-group-background",
  platform: "ios",
  width: 390,
  app: { ...NATIVE_HOME, path: "/student/settings" },
  async run(page) {
    const settings = page.getByRole("dialog", { name: "Settings" })
    await settings.waitFor()
    const r = await settings.evaluate((el) => ({
      sheet: getComputedStyle(el).backgroundColor,
      group: getComputedStyle(el.querySelector("[data-list-group]")).backgroundColor,
    }))
    await page.keyboard.press("Escape")
    await settings.waitFor({ state: "detached" })
    await page.goto(new URL("/student", page.url()).href, { waitUntil: "networkidle" })
    const dialog = await openMore(page)
    const more = await dialog.evaluate((el) => ({
      sheet: getComputedStyle(el).backgroundColor,
      group: getComputedStyle(el.querySelector("[data-list-group]")).backgroundColor,
    }))
    if (r.group !== more.group) throw new Error(`settings group ${r.group} differs from the More group ${more.group}`)
    if (r.sheet !== more.sheet) throw new Error(`settings sheet ${r.sheet} differs from the More sheet ${more.sheet}`)
  },
})
