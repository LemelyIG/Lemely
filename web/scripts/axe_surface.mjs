/*
 * A targeted axe check for one registered capture surface (P7.1).
 *
 * ── Why this exists beside `audit.mjs` ────────────────────────────────────
 *
 * `audit.mjs` is the corpus: 41 routes, real backend, real seeded data, axe
 * plus Lighthouse plus screenshots, about forty minutes. That is the right
 * instrument for a phase gate and the wrong one for "I changed a heading level
 * on one panel, did it do what I said".
 *
 * This runs axe against a single surface from `capture_surface.mjs`'s registry,
 * using that registry's own stubs, so it needs no backend and finishes in
 * seconds. It is a check, not a gate: it can only see what one surface's stub
 * data renders, which is exactly why it does not replace the corpus.
 *
 * Usage:  node scripts/axe_surface.mjs <surface> [state]
 */

import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"
import { SURFACES, SESSION, PROFILE, BASE, PORT } from "./capture_surface.mjs"
import { assertPortFree, startPreview } from "./serve_guard.mjs"

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const surfaceName = process.argv[2]
const onlyState = process.argv[3]

if (!surfaceName || !SURFACES[surfaceName]) {
  console.error(`usage: node scripts/axe_surface.mjs <surface> [state]`)
  console.error(`known: ${Object.keys(SURFACES).join(", ")}`)
  process.exit(2)
}

const AXE = "node_modules/axe-core/axe.min.js"

async function main() {
  await assertPortFree(BASE, PORT, "the surface axe check")
  const preview = startPreview(PORT, path.join(repoRoot, "web"))
  try {
    const deadline = Date.now() + 30_000
    for (;;) {
      if (preview.child.exitCode !== null) throw new Error(preview.log())
      try {
        if ((await fetch(BASE, { signal: AbortSignal.timeout(2000) })).ok) break
      } catch {
        /* not up yet */
      }
      if (Date.now() > deadline) throw new Error(`preview never answered\n${preview.log()}`)
      await new Promise((r) => setTimeout(r, 300))
    }

    const surface = SURFACES[surfaceName]
    const browser = await chromium.launch()
    let total = 0

    for (const [stateName, state] of Object.entries(surface.states)) {
      if (onlyState && stateName !== onlyState) continue
      const session = surface.session === null ? null : { ...SESSION, ...(surface.session ?? {}) }
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
      await context.addInitScript(
        ([sess, key]) => {
          if (sess === null) window.localStorage.removeItem(key)
          else window.localStorage.setItem(key, JSON.stringify(sess))
          window.localStorage.setItem("lemely.deviceId", "axe-device")
        },
        [session, "lemely.session"],
      )
      const page = await context.newPage()
      await page.route("**/api/**", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      )
      await page.route("**/api/me/profile", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...PROFILE, ...(surface.profile ?? {}) }),
        }),
      )
      await surface.stub(page, state)
      await page.goto(`${BASE}${surface.route}`, { waitUntil: "domcontentloaded" })
      await page.waitForTimeout(1100)
      if (surface.act) await surface.act(page, state)
      await page.addScriptTag({ path: path.join(repoRoot, "web", AXE) })
      const result = await page.evaluate(async () => await window.axe.run())

      for (const v of result.violations) {
        total += v.nodes.length
        console.log(`${stateName}  ${v.impact}  ${v.id}  (${v.nodes.length})`)
        for (const n of v.nodes.slice(0, 2)) console.log(`    ${n.html.slice(0, 120)}`)
      }
      if (result.violations.length === 0) console.log(`${stateName}  clean`)
      await context.close()
    }

    await browser.close()
    console.log(`\n${surfaceName}: ${total} violation node(s)`)
    if (total > 0) process.exitCode = 1
  } finally {
    preview.stop()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
