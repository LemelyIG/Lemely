/*
 * Phase 6.1 `adapt` gate — the mobile non-negotiables, measured.
 *
 * REDESIGN-MISSION.md §6.1 asks for every page "verified at 320 / 375 / 414 /
 * 768 px and desktop", with five hallmark non-negotiables enforced: no
 * horizontal scroll, no two-line clickable text, `minmax(0,1fr)` on grid
 * tracks, `overflow-wrap:anywhere` on display headers, and touch targets
 * >=44x44 with >=8px spacing.
 *
 * WHY THIS IS NOT A SCREENSHOT ROUND.
 *
 * Four of those five are invisible in a picture. A 40px-tall button and a 44px
 * one are the same button on screen; two controls 6px apart look fine; a
 * heading that will break a long token badly only does so for the one student
 * whose data contains one. `capture_surface.mjs` renders and this measures, and
 * the phase needs both. This walks the SAME registry that harness does —
 * imported, never restated — because P4.10's finding was that a hand-maintained
 * gate list is a list some screen is missing from.
 *
 * THE ONE CHECK THAT MUST NOT BE WRITTEN THE OBVIOUS WAY.
 *
 * The obvious horizontal-scroll test is
 * `document.documentElement.scrollWidth > clientWidth`. In this codebase that
 * expression can never be true: `index.css` sets `overflow-x: clip` on html and
 * body, which is itself one of the non-negotiables, and clipping suppresses the
 * scroll it is asked about. A gate written that way passes on every page
 * forever, including pages whose content is being silently cut off the side —
 * and silent truncation is worse than a scrollbar, because a scrollbar tells
 * the reader something is there.
 *
 * So overflow is measured off element geometry instead: an element is a
 * violation if its border box crosses the viewport edge and no ancestor
 * BETWEEN it and <body> establishes its own clipping or scrolling context. The
 * ancestor exemption is what separates real page overflow from a table or a
 * scroller that is deliberately clipping its own children. html and body are
 * excluded from that exemption on purpose: their `clip` is precisely the mask
 * this check exists to see through.
 *
 * Usage:  node scripts/adapt_audit.mjs [--surface=<name>] [--json=<path>]
 * Assumes `npm run build` has run; serves `dist/`.
 */

import { spawn } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"

import { SURFACES, SESSION, PROFILE } from "./capture_surface.mjs"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..", "..")
const PORT = 4321
const BASE = `http://127.0.0.1:${PORT}`

/**
 * §6.1's four mobile widths plus desktop. 320 is the floor the mission names
 * and is not academic: it is the iPhone SE / Galaxy Fold cover width, and it is
 * where a layout that merely "works on mobile" stops working.
 */
const WIDTHS = [
  { name: "320", width: 320, height: 900, touch: true },
  { name: "375", width: 375, height: 900, touch: true },
  { name: "414", width: 414, height: 900, touch: true },
  { name: "768", width: 768, height: 1000, touch: true },
  { name: "1440", width: 1440, height: 1000, touch: false },
]

const args = process.argv.slice(2)
const onlySurface = args.find((a) => a.startsWith("--surface="))?.split("=")[1]
const jsonPath = args.find((a) => a.startsWith("--json="))?.split("=")[1]

/**
 * Runs inside the page. Returns plain data only — nothing here may reference a
 * Node binding.
 *
 * `touch` gates the 44x44 and 8px-spacing rules to the four mobile widths. Those
 * are finger rules; applying them at 1440 would flag every dense table control
 * in the teacher and admin portals, which are the surfaces §3.3 deliberately
 * sets to DENSITY 7 for a mouse.
 */
function measure({ touch }) {
  const vw = window.innerWidth
  const out = {
    overflow: [],
    twoLine: [],
    smallTarget: [],
    exemptTarget: [],
    exemptPair: [],
    tightPair: [],
    badWrap: [],
  }

  const describe = (el) => {
    const id = el.id ? `#${el.id}` : ""
    const cls =
      typeof el.className === "string" && el.className
        ? "." + el.className.trim().split(/\s+/).slice(0, 4).join(".")
        : ""
    const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 48)
    return `${el.tagName.toLowerCase()}${id}${cls}${text ? ` [${text}]` : ""}`
  }

  const visible = (el, rect) => {
    if (rect.width === 0 || rect.height === 0) return false
    const cs = getComputedStyle(el)
    if (cs.visibility === "hidden" || cs.display === "none" || cs.opacity === "0") return false
    // Screen-reader-only text is deliberately a 1px clipped box off in a
    // corner; it is not a layout participant and must not read as overflow.
    if (cs.clipPath !== "none" && rect.width <= 2 && rect.height <= 2) return false
    if (el.closest("[aria-hidden='true']")) return false
    return true
  }

  const all = Array.from(document.body.querySelectorAll("*"))

  /* ── 1. Horizontal overflow ─────────────────────────────────────────── */
  const clipped = (el) => {
    // Walk STRICTLY between el and body. html/body are excluded on purpose:
    // their `overflow-x: clip` is the mask this check sees through.
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p)
      if (/hidden|clip|auto|scroll/.test(cs.overflowX)) return true
      // A fixed/absolute descendant of a transformed box is positioned against
      // that box, so its rect is not evidence about the page.
      if (cs.transform !== "none" && getComputedStyle(el).position === "fixed") return true
    }
    return false
  }
  const offenders = []
  for (const el of all) {
    const rect = el.getBoundingClientRect()
    if (!visible(el, rect)) continue
    // 1px of tolerance: subpixel layout rounding is not a design defect.
    const over = rect.right > vw + 1 || rect.left < -1
    if (!over) continue
    if (clipped(el)) continue
    offenders.push({ el, rect })
  }
  // An overflowing container reports every descendant too. Keep only the
  // outermost offenders, so the finding names the cause rather than the symptom.
  for (const o of offenders) {
    if (offenders.some((other) => other !== o && other.el.contains(o.el))) continue
    out.overflow.push({
      el: describe(o.el),
      right: Math.round(o.rect.right),
      left: Math.round(o.rect.left),
      viewport: vw,
    })
  }

  /* ── 2. Two-line clickable text ─────────────────────────────────────── */
  const CLICKABLE = "a[href], button, [role='button'], [role='link']"
  for (const el of Array.from(document.body.querySelectorAll(CLICKABLE))) {
    const rect = el.getBoundingClientRect()
    if (!visible(el, rect)) continue
    // A link wrapping a whole card is a clickable REGION, not clickable text;
    // §6's rule is about a label breaking across lines.
    const hasBlockChild = Array.from(el.children).some((c) => {
      const d = getComputedStyle(c).display
      return d === "block" || d === "flex" || d === "grid" || d === "table"
    })
    if (hasBlockChild) continue
    const text = (el.textContent ?? "").trim()
    if (!text) continue
    // Line boxes, not height/line-height arithmetic: a Range's client rects are
    // one per rendered line, which is the thing actually being asked about.
    const range = document.createRange()
    range.selectNodeContents(el)
    const lines = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0)
    // Collapse rects that share a baseline (an inline icon beside a label
    // produces two rects on one line).
    const rows = new Set(lines.map((r) => Math.round(r.top)))
    if (rows.size > 1) {
      /*
       * §6's ban is on a LABEL breaking across lines — P4.7's "See" / "the
       * roll" is the canonical case, where the second line reads as a separate
       * control. A link whose text is content the school typed (a class name, a
       * quiz title, a study-plan topic) is a different thing: the only ways to
       * keep it on one line are to truncate it or to let it overflow, and both
       * lose the reader information the product does not own and cannot
       * shorten. Those opt out by marking themselves, so the exemption is
       * visible in the source of the screen taking it rather than buried in a
       * list here that nobody reading the JSX would find.
       */
      if (el.closest("[data-wraps-content-title]")) continue
      out.twoLine.push({ el: describe(el), lines: rows.size, width: Math.round(rect.width) })
    }
  }

  /* ── 3/4. Touch target size and spacing ─────────────────────────────── */
  if (touch) {
    const INTERACTIVE =
      "a[href], button, input:not([type='hidden']), select, textarea, [role='button'], [role='tab'], [role='switch'], [role='checkbox'], [role='radio'], [tabindex]:not([tabindex='-1'])"
    /*
     * Measure what a finger actually aims at.
     *
     * Two controls in this product are deliberately not their own hit target:
     *
     *  - `FileDrop`'s `<input type=file>` is `sr-only` (a 1px clipped box) with
     *    the whole drop zone as its label. It measured 1x44.
     *  - `Checkbox` and `Radio` render the real input `absolute inset-0` inside
     *    an 18px painted box, the `appearance-none` technique that keeps the
     *    native control in the accessibility tree. They measured 16x16, and the
     *    44px floor in `index.css` is deliberately on the LABEL ROW instead —
     *    putting it on the input would hang a 44px invisible hit area 26px
     *    below an 18px control, overlapping the next option in a radio group.
     *
     * Reporting the input in either case measures a box no reader can see. So
     * the control is RE-POINTED at its label rather than exempted: the floor is
     * still enforced, on the element that carries it. If there is no label, the
     * control is measured as itself — an unlabelled hidden input is a real
     * defect and must not be silently dropped by an exemption written for a
     * labelled one.
     */
    const aimedAt = (el, cs) => {
      if (el.tagName !== "INPUT") return null
      const painted = cs.appearance === "none" || cs.webkitAppearance === "none"
      const clipped = cs.clipPath !== "none" || cs.position === "absolute"
      if (!painted && !clipped) return null
      /*
       * A control may have MORE than one label bound to it, and then "the
       * label" is the wrong question. `FileDrop` binds two: a 13px caption
       * ("Scanned paper") and the drop zone itself, which is the thing a finger
       * lands on. `querySelector` returns whichever comes first in document
       * order — the caption — so the gate spent a full run reporting the
       * product's largest tap target as its smallest, 40 times.
       *
       * The floor asks whether there is something 44x44 to aim at, so where
       * several labels are bound, aim at the biggest. Picking by area rather
       * than by document order is what makes that answer independent of markup
       * order.
       */
      const labels = el.id
        ? Array.from(document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`))
        : []
      const own = el.closest("label")
      if (own && !labels.includes(own)) labels.push(own)
      const rects = labels
        .map((l) => ({ el: l, rect: l.getBoundingClientRect() }))
        .filter((c) => c.rect.width > 0 && c.rect.height > 0)
      if (rects.length === 0) return null
      return rects.reduce((a, b) =>
        b.rect.width * b.rect.height > a.rect.width * a.rect.height ? b : a,
      )
    }

    const targets = []
    const seen = new Set()
    for (const el of Array.from(document.body.querySelectorAll(INTERACTIVE))) {
      const rect = el.getBoundingClientRect()
      if (!visible(el, rect)) continue
      const cs = getComputedStyle(el)
      // An inline link inside a sentence cannot be 44px tall without breaking
      // the sentence. WCAG 2.5.5 exempts inline text for exactly this reason.
      if (cs.display === "inline") continue
      const target = aimedAt(el, cs) ?? { el, rect }
      // A label re-pointed to by two of its own inputs is one target, not two.
      if (seen.has(target.el)) continue
      seen.add(target.el)
      // Nested controls (a button inside a labelled row) would double-count.
      // `exempt` is carried on the target so the spacing rule below can honour
      // the same call-site waiver the size rule does; see the pair loop.
      target.exempt = el.closest("[data-touch-floor-exempt]") ?? null
      targets.push(target)
      /*
       * 0.5px of tolerance, and it is not a softening of the rule.
       *
       * An element whose CSS floor is exactly `min-block-size: 44px` measures
       * 43.95-44.0 depending on the fractional y-offset it happens to land on,
       * because Chromium lays out in 1/64px LayoutUnits. Without tolerance the
       * gate reported one or two such elements per run, in a DIFFERENT state
       * each time — three consecutive runs of `teacher-analytics` gave one
       * finding, then two, then a different element. A gate whose result
       * changes between identical runs teaches people to re-run it until it
       * passes, which costs more than the vacuous gate this file replaced: that
       * one was at least consistently wrong.
       *
       * Half a pixel is well under any real miss. The genuine sub-pixel defect
       * this same run found — a link padded to 43.7px by hand — is still caught
       * with 0.3px to spare, and every other real finding was 20px or shorter.
       */
      const FLOOR = 44 - 0.5
      if (target.rect.width < FLOOR || target.rect.height < FLOOR) {
        /*
         * A control whose geometry the floor genuinely cannot have, marked at
         * the call site with the reason. It is reported as `exemptTarget`, not
         * dropped: a silent exemption is how a gate stops meaning anything, and
         * the run's own summary should say how many controls it let through.
         *
         * The one case today is the six-box OTP row. Six 44px boxes plus five
         * gaps need 284px of inline space and the card offers ~248px at the
         * 320px viewport, so the floor is arithmetically unreachable there.
         * They are 56px TALL, they tile the row edge to edge with no dead space
         * between them, and a mis-tap lands on an adjacent digit box, which is
         * visible and recoverable. Shrinking to five boxes or scrolling a code
         * entry sideways would both be worse.
         */
        /*
         * Reported to 0.1px, not rounded to whole pixels. The comparison above
         * is on the raw float, so a 43.6px-tall box fails the floor and then
         * printed as "44" — a finding that reads as though the gate were wrong
         * about its own rule. Sub-pixel misses are a real and distinct class
         * here (a line-height that lands just under the floor, rather than a
         * control nobody sized), and telling them apart from a 20px back link
         * is the difference between one fix and thirty.
         */
        const px = (n) => Math.round(n * 10) / 10
        if (el.closest("[data-touch-floor-exempt]")) {
          out.exemptTarget.push({
            el: describe(target.el),
            w: px(target.rect.width),
            h: px(target.rect.height),
            reason: el.closest("[data-touch-floor-exempt]").dataset.touchFloorExempt || "unstated",
          })
          continue
        }
        out.smallTarget.push({
          el: describe(target.el),
          w: px(target.rect.width),
          h: px(target.rect.height),
        })
      }
    }
    for (let i = 0; i < targets.length; i++) {
      for (let j = i + 1; j < targets.length; j++) {
        const a = targets[i]
        const b = targets[j]
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue
        const dx = Math.max(0, Math.max(a.rect.left - b.rect.right, b.rect.left - a.rect.right))
        const dy = Math.max(0, Math.max(a.rect.top - b.rect.bottom, b.rect.top - a.rect.bottom))
        // Only adjacent-in-one-axis pairs matter: two controls diagonally
        // apart are not a mis-tap risk.
        if (dx > 0 && dy > 0) continue
        const gap = Math.max(dx, dy)
        // Spacing only matters between targets that are already tight to hit.
        // Two full-width list rows sharing an edge have a 0px gap by design and
        // are not a mis-tap risk; that is what a list looks like. The rule is
        // there to stop a SMALL control being crowded, so it fires only when at
        // least one of the pair already fails the 44x44 floor. Without this the
        // gate reports every stacked row in the product and means nothing.
        // Same 0.5px tolerance as the floor above, and for the same reason: a
        // control that passes the floor must not then count as "tiny" here, or
        // the spacing rule would fire on pairs the size rule just cleared.
        const tiny = (r) => r.width < 44 - 0.5 || r.height < 44 - 0.5
        if (!tiny(a.rect) && !tiny(b.rect)) continue
        if (gap < 8) {
          /*
           * A waiver stated at the call site has to cover BOTH rules, or it is
           * not a waiver. The six-box OTP row is exempt from the size floor
           * because six 44px boxes plus five gaps need 284px and the card
           * offers ~248px at 320px — and the same arithmetic is exactly why
           * they sit 4px apart. Honouring the exemption on size and then
           * failing the same control on spacing reported 30 findings that no
           * edit could clear without undoing the reason for the exemption.
           *
           * Only when BOTH are exempt. One exempt control crowding a normal one
           * is still a real mis-tap risk, and the waiver was written about the
           * digit boxes among themselves — a mis-tap there lands on an adjacent
           * digit, which is visible and recoverable. It stays REPORTED, on the
           * same principle as `exemptTarget`: a gate that hides its carve-outs
           * stops meaning anything.
           */
          if (a.exempt && b.exempt && a.exempt === b.exempt) {
            out.exemptPair.push({
              a: describe(a.el),
              b: describe(b.el),
              gap: Math.round(gap * 10) / 10,
              reason: a.exempt.dataset.touchFloorExempt || "unstated",
            })
            continue
          }
          out.tightPair.push({ a: describe(a.el), b: describe(b.el), gap: Math.round(gap) })
        }
      }
    }
  }

  /* ── 5. overflow-wrap on display headers ────────────────────────────── */
  /*
   * Display rungs only. The data rungs were in this selector for one run and
   * are deliberately out: see the note beside the rule in `index.css` for why a
   * mark must overflow visibly rather than wrap into a different number.
   * Headings are covered because every heading in this product carries a
   * display rung; a heading that does not is a separate defect, and the
   * geometric overflow check below catches it if it ever bites.
   */
  for (const el of Array.from(document.body.querySelectorAll("[class*='text-display-']"))) {
    const rect = el.getBoundingClientRect()
    if (!visible(el, rect)) continue
    const cs = getComputedStyle(el)
    const wrap = cs.overflowWrap || cs.wordWrap
    if (wrap !== "anywhere" && wrap !== "break-word") {
      out.badWrap.push({ el: describe(el), overflowWrap: wrap })
    }
  }

  return out
}

function serveDist() {
  return spawn(
    "npx",
    ["vite", "preview", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: path.join(repoRoot, "web"), stdio: ["ignore", "pipe", "pipe"] },
  )
}

async function waitForServer(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(2000) })
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`vite preview did not answer on ${BASE} within ${timeoutMs}ms`)
}

async function main() {
  const names = onlySurface ? [onlySurface] : Object.keys(SURFACES)
  for (const n of names) {
    if (!SURFACES[n]) throw new Error(`unknown surface "${n}"`)
  }

  const server = serveDist()
  const findings = []
  let checks = 0
  try {
    await waitForServer()
    const browser = await chromium.launch()

    for (const surfaceName of names) {
      const surface = SURFACES[surfaceName]
      for (const vp of WIDTHS) {
        for (const [stateName, state] of Object.entries(surface.states)) {
          const session =
            surface.session === null ? null : { ...SESSION, ...(surface.session ?? {}) }
          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
            deviceScaleFactor: 1,
            /*
             * The 44x44 floor is a FINGER rule, not a window-width rule, so the
             * fix for it is written against `(pointer: coarse)` and this has to
             * present as a finger or the gate would be measuring a page the fix
             * does not apply to. Verified rather than assumed: with
             * `hasTouch: true` Chromium reports `(pointer: coarse)` true and
             * `(pointer: fine)` false; with it false, the reverse.
             */
            hasTouch: vp.touch,
          })
          await context.addInitScript(
            ([sess, key]) => {
              if (sess === null) window.localStorage.removeItem(key)
              else window.localStorage.setItem(key, JSON.stringify(sess))
              window.localStorage.setItem("lemely.deviceId", "capture-device")
            },
            [session, "lemely.session"],
          )
          const page = await context.newPage()
          // Registration order is load-bearing; see capture_surface.mjs.
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
          await page.waitForTimeout(state.delayMs ? 700 : 1100)
          if (surface.act) await surface.act(page, state)

          const result = await page.evaluate(measure, { touch: vp.touch })
          checks++
          const where = `${surfaceName}/${stateName}@${vp.name}`
          for (const kind of Object.keys(result)) {
            for (const item of result[kind]) findings.push({ where, kind, ...item })
          }
          await context.close()
        }
      }
      process.stdout.write(`. ${surfaceName}\n`)
    }
    await browser.close()
  } finally {
    server.kill("SIGTERM")
  }

  /*
   * `exemptTarget` is reported but does not fail the run. It is printed on its
   * own line, with the reason and the distinct call sites, so that "how many
   * controls did this let through, and why" is answered by every run rather
   * than by reading the source. A gate that hides its own carve-outs is the
   * vacuous-gate defect wearing a different hat.
   */
  const EXEMPT_KINDS = new Set(["exemptTarget", "exemptPair"])
  const exempt = findings.filter((f) => EXEMPT_KINDS.has(f.kind))
  const failures = findings.filter((f) => !EXEMPT_KINDS.has(f.kind))

  const byKind = {}
  for (const f of failures) byKind[f.kind] = (byKind[f.kind] ?? 0) + 1
  console.log(`\n${checks} page-states measured across ${names.length} surfaces.`)
  console.log(`${failures.length} findings:`, JSON.stringify(byKind))
  if (exempt.length) {
    const reasons = {}
    for (const e of exempt) reasons[e.reason] = (reasons[e.reason] ?? 0) + 1
    console.log(`${exempt.length} exempt (stated at the call site):`, JSON.stringify(reasons))
  }

  if (jsonPath) {
    const abs = path.resolve(jsonPath)
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, JSON.stringify({ checks, byKind, findings }, null, 2), "utf8")
    console.log(`wrote ${path.relative(repoRoot, abs)}`)
  }
  if (failures.length) process.exitCode = 1
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
