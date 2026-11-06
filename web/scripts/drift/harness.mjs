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

/** The content box (padding excluded) of `selector`, in page coordinates. */
export async function contentBox(page, selector) {
  return page.$eval(selector, (el) => {
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    const pl = parseFloat(s.paddingLeft)
    const pr = parseFloat(s.paddingRight)
    const pt = parseFloat(s.paddingTop)
    const pb = parseFloat(s.paddingBottom)
    return {
      x: Math.round(r.left + pl),
      y: Math.round(r.top + window.scrollY + pt),
      width: Math.round(r.width - pl - pr),
      height: Math.max(1, Math.round(el.scrollHeight - pt - pb)),
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
 * frame: the viewport, with the page content hidden (layout kept), so only the
 * shell and any panel or dialog over it is compared.
 * content: the content box only; `neutral` paints its own background magenta on
 * both sides so a shell background change cannot leak into a content compare.
 */
export async function capture(page, { capture: mode, selector, neutral = false }) {
  if (mode === "frame") {
    await page.addStyleTag({ content: `${selector} > * { visibility: hidden !important; }` })
    return page.screenshot({ animations: "disabled", caret: "hide" })
  }
  if (neutral) await page.addStyleTag({ content: `${selector} { background: rgb(255 0 255) !important; }` })
  const clip = await contentBox(page, selector)
  return page.screenshot({ fullPage: true, clip, animations: "disabled", caret: "hide" })
}
