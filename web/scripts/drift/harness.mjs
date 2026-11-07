/*
 * Page and server setup for the drift gate and the shell behaviour runner.
 *
 * App side: the production build served by `vite preview` (run `npm run build`
 * first), every `/api/**` call mocked, so no backend is needed. Preview side:
 * the design kit dev server (`vite --config vite.preview.config.ts`) serving
 * `student-home-a.html`. Both sides get the same viewport, theme, frozen clock
 * (2026-11-05 10:00, the preview fixtures' "now") and no animation.
 */
import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { PNG } from "pngjs"
import { SURFACES, SESSION, PROFILE } from "../capture_surface.mjs"
import { assertPortFree, startPreview } from "../serve_guard.mjs"

export const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
export const REPO_DIR = path.resolve(WEB_DIR, "..")
export const APP_PORT = 4321
export const APP_BASE = `http://127.0.0.1:${APP_PORT}`
export const KIT_PORT = 5180
export const KIT_BASE = `http://127.0.0.1:${KIT_PORT}`
export const NOW = new Date(2026, 10, 5, 10, 0)
export const SELECTORS = { app: "#main-content", preview: "#as-main" }

const STILL_CSS =
  "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
const PREVIEW_CSS = ".sh-toolbar{display:none!important}.sh-root{--as-top:0px!important}"

async function waitUntilUp(url, proc, label) {
  const deadline = Date.now() + 60_000
  for (;;) {
    if (proc.child.exitCode !== null) throw new Error(`${label} exited\n${proc.log()}`)
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(2000) })).ok) return
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) throw new Error(`${label} never answered\n${proc.log()}`)
    await new Promise((r) => setTimeout(r, 300))
  }
}

export async function startServers({ needKit }) {
  await assertPortFree(APP_BASE, APP_PORT, "the drift gate")
  const app = startPreview(APP_PORT, WEB_DIR)
  try {
    await waitUntilUp(APP_BASE, app, "app preview")
    return await startKit(app, needKit)
  } catch (error) {
    app.stop()
    throw error
  }
}

const DEV_DIR = path.join(WEB_DIR, "dev-previews")

/** Drop <script> blocks (Vite rewrites them in dev) and collapse whitespace. */
function markupOnly(text) {
  return text.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "").replace(/\s+/g, " ").trim()
}

const sha = (buffer) => createHash("sha256").update(buffer).digest("hex").slice(0, 12)

/**
 * Files whose served bytes identify the kit. CSS is fetched with `?direct`,
 * which Vite serves untransformed. The HTML entry is always transformed (client
 * and refresh scripts injected, inline script moved), so only its script-free
 * markup is compared.
 */
export const KIT_PROBES = [
  { url: "/student-home/variant-a.css?direct", file: "student-home/variant-a.css" },
  { url: "/student-home/tokens.css?direct", file: "student-home/tokens.css" },
  { url: "/student-home-a.html", file: "student-home-a.html", digest: (buf) => sha(markupOnly(buf.toString("utf8"))) },
]

/**
 * Probe KIT_PORT. Returns false when nothing answers there; true when the
 * server there serves THIS worktree's kit; throws otherwise. "Serves this
 * worktree" = every KIT_PROBES file hashes the same as on disk. (The design
 * preview server is long-lived and may belong to another worktree, in which
 * case the gate must not silently use it.)
 */
export async function verifyRunningKit(fetchImpl = fetch) {
  const mismatches = []
  for (const probe of KIT_PROBES) {
    const digest = probe.digest ?? sha
    let res
    try {
      res = await fetchImpl(`${KIT_BASE}${probe.url}`, { signal: AbortSignal.timeout(1500) })
    } catch {
      return false
    }
    if (!res.ok) return false
    const served = digest(Buffer.from(await res.arrayBuffer()))
    const disk = digest(fs.readFileSync(path.join(DEV_DIR, probe.file)))
    if (served !== disk) mismatches.push(`${probe.file} served hash ${served}, on-disk hash ${disk}`)
  }
  if (mismatches.length) {
    throw new Error(
      `port ${KIT_PORT} serves a design kit that is not this worktree (${WEB_DIR}): ` +
        `${mismatches.join("; ")}. ` +
        `Stop that server or run it from this worktree; the gate will not start a second kit.`,
    )
  }
  return true
}

async function startKit(app, needKit) {
  let kit = null
  if (needKit && !(await verifyRunningKit())) {
    await assertPortFree(KIT_BASE, KIT_PORT, "the drift gate")
    const bin = path.join(WEB_DIR, "node_modules", ".bin", "vite")
    const child = spawn(
      bin,
      ["--config", "vite.preview.config.ts", "--port", String(KIT_PORT), "--strictPort", "--host", "127.0.0.1"],
      { cwd: WEB_DIR, stdio: ["ignore", "pipe", "pipe"] },
    )
    const lines = []
    child.stdout.on("data", (d) => lines.push(String(d)))
    child.stderr.on("data", (d) => lines.push(String(d)))
    kit = { child, log: () => lines.join(""), stop: () => child.kill("SIGTERM") }
    try {
      await waitUntilUp(`${KIT_BASE}/student-home-a.html`, kit, "preview kit")
    } catch (error) {
      kit.stop()
      throw error
    }
  }
  return {
    stop() {
      app.stop()
      kit?.stop()
    },
  }
}

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

async function newContext(browser, { width, height, theme }) {
  return browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: theme,
  })
}

/** Open the real app at a route with mocked API and the scene's theme. */
export async function openApp(browser, { width, height, theme, app }) {
  const surface = app.surface ? SURFACES[app.surface] : null
  if (app.surface && !surface) throw new Error(`unknown capture surface ${app.surface}`)
  const session = { ...SESSION, ...(surface?.session ?? {}), ...(app.session ?? {}) }
  const profile = { ...PROFILE, ...(surface?.profile ?? {}), ...(app.profile ?? {}) }
  const context = await newContext(browser, { width, height, theme })
  await context.addInitScript(
    ([sess, chosenTheme]) => {
      window.localStorage.setItem("lemely.session", JSON.stringify(sess))
      window.localStorage.setItem("lemely.deviceId", "drift-device")
      window.localStorage.setItem("lemely.theme", chosenTheme)
    },
    [session, theme],
  )
  const page = await context.newPage()
  await page.clock.setFixedTime(NOW)
  // Registration order matters: Playwright tries the most recent route first.
  await page.route("**/api/**", (route) => json(route, {}))
  await page.route("**/api/me/profile", (route) => json(route, profile))
  if (surface) await surface.stub(page, surface.states[app.state ?? Object.keys(surface.states)[0]])
  if (app.mocks) await app.mocks(page)
  await page.goto(`${APP_BASE}${app.path ?? surface.route}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: STILL_CSS })
  await page.evaluate(() => document.fonts.ready)
  if (app.act) await app.act(page, { width, theme })
  await page.waitForTimeout(150)
  return { context, page }
}

/** Open the design A preview in a state, with its toolbar removed. */
export async function openPreview(browser, { width, height, theme, preview }) {
  const context = await newContext(browser, { width, height, theme })
  const page = await context.newPage()
  await page.clock.setFixedTime(NOW)
  const query = new URLSearchParams({ state: preview.state, theme, motion: "reduce", width: "desktop" })
  await page.goto(`${KIT_BASE}/student-home-a.html?${query}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: STILL_CSS + PREVIEW_CSS })
  await page.evaluate(() => document.fonts.ready)
  if (preview.act) await preview.act(page, { width, theme })
  await page.waitForTimeout(150)
  return { context, page }
}

/**
 * The content box (padding excluded) of `selector`, in page coordinates. Its
 * height is the painted extent: the content box bottom, or any visible, non-fixed
 * descendant's border-box bottom plus its ink reach (box-shadow offsetY + 1.5 x
 * blur + spread, Skia rasterises a blur out to 3 sigma; outline width + offset;
 * filter drop-shadow), or any text line's bottom plus its text-shadow reach,
 * whichever is lowest, rounded up. Not counted: ::before/::after box-shadow and
 * outline (a pseudo-element's own geometry is not exposed by the DOM; its layout
 * box still grows scrollHeight). Clipped or sr-only text can inflate the extent;
 * that is harmless, the extra rows are neutral fill on both sides. Extra painted content therefore lengthens the
 * capture (compare pads the shorter side with magenta, so it shows as a diff) and
 * pure trailing empty space under the neutral fill stays equal to the pad.
 */
export async function contentBox(page, selector) {
  return page.$eval(selector, (el) => {
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    const pl = parseFloat(s.paddingLeft)
    const pr = parseFloat(s.paddingRight)
    const pt = parseFloat(s.paddingTop)
    const pb = parseFloat(s.paddingBottom)
    const top = r.top + pt
    let bottom = top + Math.max(1, el.scrollHeight - pt - pb)
    const shadowReach = (value) => {
      // box-shadow / text-shadow lists: split on commas outside parentheses, skip inset, read the px lengths after dropping the colour function.
      if (!value || value === "none") return 0
      const parts = []
      let depth = 0
      let cur = ""
      for (const ch of value) {
        if (ch === "(") depth++
        if (ch === ")") depth--
        if (ch === "," && depth === 0) {
          parts.push(cur)
          cur = ""
        } else cur += ch
      }
      parts.push(cur)
      let reach = 0
      for (const part of parts) {
        if (/\binset\b/.test(part)) continue
        const nums = (part.replace(/(rgba?|hsla?|color|oklch|oklab|lab|lch)\([^)]*\)/g, "").match(/-?[\d.]+px/g) ?? []).map(parseFloat)
        const [, oy = 0, blur = 0, spread = 0] = nums
        reach = Math.max(reach, oy + 1.5 * blur + spread)
      }
      return reach
    }
    const inkReach = (cs) => {
      let reach = Math.max(0, shadowReach(cs.boxShadow))
      if (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) {
        reach = Math.max(reach, parseFloat(cs.outlineWidth) + Math.max(0, parseFloat(cs.outlineOffset) || 0))
      }
      for (const m of cs.filter.matchAll(/drop-shadow\(([^)]*(?:\([^)]*\))?[^)]*)\)/g)) reach = Math.max(reach, shadowReach(m[1]))
      return reach
    }
    const fixed = new Map()
    const underFixed = (node) => {
      if (node === el) return false
      if (fixed.has(node)) return fixed.get(node)
      const out = getComputedStyle(node).position === "fixed" || underFixed(node.parentElement)
      fixed.set(node, out)
      return out
    }
    for (const d of el.querySelectorAll("*")) {
      const cs = getComputedStyle(d)
      if (cs.display === "none" || cs.visibility === "hidden" || underFixed(d)) continue
      const dr = d.getBoundingClientRect()
      if (!(dr.width > 0 && dr.height > 0)) continue
      bottom = Math.max(bottom, dr.bottom + inkReach(cs))
    }
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    const range = document.createRange()
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const parent = n.parentElement
      if (!n.nodeValue.trim() || !parent || underFixed(parent)) continue
      const ps = getComputedStyle(parent)
      if (ps.display === "none" || ps.visibility === "hidden") continue
      range.selectNodeContents(n)
      const textReach = Math.max(0, shadowReach(ps.textShadow))
      for (const tr of range.getClientRects()) if (tr.width > 0 && tr.height > 0) bottom = Math.max(bottom, tr.bottom + textReach)
    }
    // Height from the rounded y, the same coordinate the clip starts at.
    const y = Math.round(r.top + window.scrollY + pt)
    return {
      x: Math.round(r.left + pl),
      y,
      width: Math.round(r.width - pl - pr),
      height: Math.max(1, Math.ceil(bottom + window.scrollY) - y),
    }
  })
}

/** Resize the window until the content box is `target` px wide. */
export async function matchContentWidth(page, selector, target, height) {
  for (let i = 0; i < 8; i++) {
    const box = await contentBox(page, selector)
    const delta = target - box.width
    if (delta === 0) return true
    const vp = page.viewportSize()
    await page.setViewportSize({ width: vp.width + delta, height })
    await page.waitForTimeout(80)
  }
  return false
}

/**
 * Pin the content box of `selector` to `target` px wide at the window's native
 * width, so viewport media queries stay identical to the baseline's. Inline
 * width and max-width on the element (border-box, padding added back).
 */
export async function pinContentWidth(page, selector, target) {
  await page.$eval(
    selector,
    (el, w) => {
      const s = getComputedStyle(el)
      const total = w + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight)
      el.style.setProperty("box-sizing", "border-box", "important")
      el.style.setProperty("width", `${total}px`, "important")
      el.style.setProperty("max-width", `${total}px`, "important")
      el.style.setProperty("flex-shrink", "0", "important")
    },
    target,
  )
  await page.waitForTimeout(80)
  return (await contentBox(page, selector)).width === target
}

/**
 * frame: the viewport, with the page content hidden (layout kept), so only the
 * shell and any panel or dialog over it is compared.
 * content: the content box only; `neutral` paints its own background magenta on
 * both sides so a shell background change cannot leak into a content compare.
 */
export async function capture(page, { capture: mode, selector, neutral = false, originX }) {
  if (mode === "frame") {
    await page.addStyleTag({ content: `${selector} > * { visibility: hidden !important; }` })
    return { png: await stableShot(page, () => page.screenshot({ animations: "disabled", caret: "hide" })), x: undefined }
  }
  if (neutral) await page.addStyleTag({ content: `html, body, ${selector} { background: rgb(255 0 255) !important; }` })
  await hideChromeOutside(page, selector)
  await snapContentOrigin(page, selector, originX)
  const clip = await contentBox(page, selector)
  const png = await stableShot(page, () => page.screenshot({ fullPage: true, clip, animations: "disabled", caret: "hide" }))
  return { png, x: clip.x }
}

/**
 * Horizontal overflow at the window's natural layout: the document or the
 * content root scrolls sideways (scrollWidth > clientWidth). Returns the
 * overflowing parts (empty when none). Width pinning proves content equivalence
 * at the baseline width only; this is the cheap check on the real layout.
 */
export async function horizontalOverflow(page, selector) {
  return page.evaluate((sel) => {
    const out = []
    const doc = document.documentElement
    if (doc.scrollWidth > doc.clientWidth) out.push(`document scrollWidth ${doc.scrollWidth} > clientWidth ${doc.clientWidth}`)
    const el = document.querySelector(sel)
    if (el && el.scrollWidth > el.clientWidth) out.push(`${sel} scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}`)
    return out
  }, selector)
}

/**
 * Content mode compares page content only. A fixed or sticky element outside
 * the content selector (top bar, bottom tabs, scrim) is shell, not content, yet
 * a fullPage screenshot paints it over whatever row of the content it happens
 * to sit on, so a shell change would leak in as a content difference. Hide each
 * one with `visibility: hidden` (layout is kept, so nothing reflows). An
 * element that contains the selector is left alone.
 * Shell-over-content overlap is the frame scenes' job, not this mode's.
 */
export async function hideChromeOutside(page, selector) {
  return page.evaluate((sel) => {
    const target = document.querySelector(sel)
    let hidden = 0
    for (const el of document.body.querySelectorAll("*")) {
      if (el === target || target.contains(el)) continue
      const position = getComputedStyle(el).position
      if (position !== "fixed" && position !== "sticky") continue
      if (el.contains(target)) continue
      el.style.setProperty("visibility", "hidden", "important")
      hidden++
    }
    return hidden
  }, selector)
}

/**
 * The content origin can sit at a fractional pixel (a rem or line-height
 * above it), and a shell change moves that fraction. The clip is cut at whole
 * pixels, so a different fraction re-rasterises every anti-aliased edge in the
 * content (rounded corners, text) though nothing in it changed. Shift the
 * content by the fraction (a `translate`, no reflow) so its origin is whole on
 * both sides and only a real difference remains.
 */
export async function snapContentOrigin(page, selector, originX) {
  return page.evaluate(({ sel, originX }) => {
    const el = document.querySelector(sel)
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    const x = r.left + parseFloat(s.paddingLeft)
    const y = r.top + window.scrollY + parseFloat(s.paddingTop)
    const dx = x - Math.round(x)
    const dy = y - Math.round(y)
    // `originX`: anti-aliased edges (chart lines, rounded corners) rasterise
    // with +-1 channel noise that depends on the absolute x of the content, so a
    // shell that moves the content column sideways (sidebar 252 -> 216 px, or a
    // drawer in place of the column) leaks 1-70 px of noise into a page that did
    // not change. The caller names the x the baseline was rastered at; the
    // content is moved there, so only real differences remain.
    const shift = originX === undefined ? 0 : originX - Math.round(x)
    if (dx !== 0 || dy !== 0 || shift !== 0) el.style.setProperty("translate", `${-dx + shift}px ${-dy}px`, "important")
    return { dx, dy, shift }
  }, { sel: selector, originX })
}

/**
 * Screenshot until two consecutive buffers are byte-identical, so a page that
 * is still swapping a skeleton for content (or finishing a late paint) is never
 * compared mid-change. Never stable within `maxTries` throws "unstable capture"
 * so the scene key fails rather than passing on a half-settled frame. This is
 * a settle, not a retry: the result is never re-taken because it differs from
 * a reference.
 */
export async function stableShot(page, take, { intervalMs = 100, maxTries = 8 } = {}) {
  let previous = await take()
  for (let attempt = 1; attempt < maxTries; attempt++) {
    await page.waitForTimeout(intervalMs)
    const next = await take()
    if (next.equals(previous)) return next
    previous = next
  }
  throw new Error(`unstable capture: no two consecutive screenshots were identical in ${maxTries} tries ${intervalMs} ms apart`)
}
