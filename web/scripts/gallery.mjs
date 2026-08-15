/*
 * P7.2 · The before/after gallery.
 *
 * REDESIGN-MISSION §5 Phase 7 item 2: "one desktop + one 375px capture per
 * major surface, old vs new (pull 'old' from the pre-redesign branch point)".
 *
 * ── Where "before" comes from, and the one honest mismatch in it ───────────
 *
 * Not from a checkout of the branch point. `reports/phase-6/screens/` is the
 * build-era corpus, committed 2026-08-12, the day before redesign Phase 0
 * opened at `ba0bf73` — so it is a rendering of exactly the tree §7.2 asks for,
 * made by the build's own harness rather than reconstructed by this one. That
 * matters beyond convenience: rebuilding a four-month-old tree to photograph it
 * would be photographing whatever that build produces *today*, with today's
 * dependency resolutions, and calling it the past.
 *
 * **The mismatch, stated rather than smoothed over: the build-era corpus was
 * captured at 380px and this one captures at 375px.** Five pixels, in the same
 * layout band, but they are not the same measurement and the report says so
 * rather than labelling both "mobile" and hoping. The desktop pair is 1440 on
 * both sides and matches exactly.
 *
 * The build-era corpus has no `K-*` or `X-*` directories because those screens
 * did not exist — the admin portal was built during the redesign (D4.10). Those
 * surfaces appear in the gallery with no "before", labelled new rather than
 * padded with a substitute.
 *
 * ── Which state ───────────────────────────────────────────────────────────
 *
 * The build-era harness captured one state per screen and called it `default`.
 * This one has 2-8 states per surface, so the gallery picks the fullest — a
 * populated screen, never a loading or error or empty one — because a
 * before/after pair is a comparison of the design language, and an empty state
 * on one side and a populated one on the other compares nothing. `PICK` is the
 * preference order and the chosen state name is written into the manifest, so
 * a reader can check what they are looking at.
 */

import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"
import { SURFACES, SESSION, PROFILE, BASE, PORT } from "./capture_surface.mjs"
import { assertPortFree, startPreview } from "./serve_guard.mjs"

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const OUT = path.join(repoRoot, "reports", "phase-7", "gallery")
const BEFORE_CORPUS = path.join(repoRoot, "reports", "phase-6", "screens")

/*
 * Major surfaces, in the mission's Phase 4 order. `before` is the build-era
 * spec ID from `docs/LEMELY_UI_SPEC.md`'s screen table; `null` means the screen
 * did not exist before the redesign.
 */
const PAIRS = [
  { surface: "student-dashboard", before: "S-06", title: "Student dashboard" },
  { surface: "subject", before: "S-08", title: "Subject overview" },
  { surface: "correct-paper", before: "S-14", title: "Marking in progress" },
  { surface: "paper-result", before: "S-15", title: "Results" },
  { surface: "practice-result", before: "S-21", title: "Practice set" },
  { surface: "flashcard-decks", before: "S-22", title: "Flashcard decks" },
  { surface: "flashcard-review", before: "S-23", title: "Flashcard review" },
  { surface: "study-plan-week", before: "S-24", title: "Study plan, week view" },
  { surface: "standings", before: "S-29", title: "Leaderboards" },
  { surface: "friends", before: "S-30", title: "Friends" },
  { surface: "profile", before: "S-31", title: "Profile, XP and streak" },
  { surface: "onboarding", before: "S-01", title: "Onboarding, subjects" },
  { surface: "teacher-overview", before: "T-01", title: "Teacher dashboard" },
  { surface: "teacher-analytics", before: "T-04", title: "Class analytics" },
  { surface: "teacher-student", before: "T-05", title: "Student detail" },
  { surface: "teacher-review", before: "T-07", title: "Review queue" },
  { surface: "teacher-quizzes", before: "T-09", title: "Quizzes" },
  { surface: "parent-children", before: "P-01", title: "Parent home" },
  { surface: "parent-overview", before: "P-02", title: "Child overview" },
  { surface: "parent-subject", before: "P-03", title: "Child subject detail" },
  { surface: "parent-weaknesses", before: "P-04", title: "Child weaknesses" },
  { surface: "login", before: "G-04", title: "Sign in" },
  { surface: "parent-login", before: "G-05", title: "Parent sign in" },
  { surface: "settings-devices", before: "G-11", title: "Account and devices" },
  { surface: "settings-notifications", before: "G-12", title: "Notification settings" },
  { surface: "landing", before: "G-01", title: "Marketing landing" },
  { surface: "not-found", before: null, title: "404" },
  { surface: "data-handling", before: null, title: "How your data is handled" },
  { surface: "school-dashboard", before: null, title: "School dashboard" },
  { surface: "school-seats", before: null, title: "Seats and student accounts" },
  { surface: "school-teachers", before: null, title: "Teachers" },
  { surface: "school-classes", before: null, title: "Classes, school-wide" },
  { surface: "platform-console", before: null, title: "Platform admin console" },
  { surface: "platform-activations", before: null, title: "Activation queue" },
  { surface: "platform-pipeline", before: null, title: "Pipeline and corpus health" },
]

/** Preference order for which state represents a surface. Never a loading,
 * error or empty state — see the header. */
const PICK = ["populated", "default", "full", "ready", "live", "graded", "review"]

const WIDTHS = [
  { name: "1440", width: 1440, height: 900, touch: false },
  { name: "375", width: 375, height: 812, touch: true },
]

/**
 * The build-era capture for one spec ID at one width.
 *
 * Not simply `default--<width>.png`: the build harness named its single state
 * per screen, and most called it `default` while a few named the thing on the
 * screen. `S-14` is `marking-in-progress--1440.png`, which the first run of
 * this script reported as a missing "before" rather than silently omitting —
 * that report is why this function exists. Error and empty states are excluded
 * for the same reason the "after" side picks the fullest state: a pair that
 * compares an error screen against a populated one compares nothing.
 */
function beforeFile(specId, width) {
  const dir = path.join(BEFORE_CORPUS, specId)
  if (!fs.existsSync(dir)) return null
  const preferred = path.join(dir, `default--${width}.png`)
  if (fs.existsSync(preferred)) return preferred
  const candidate = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(`--${width}.png`))
    .filter((f) => !/error|empty|loading|skeleton/i.test(f))
    .sort()[0]
  return candidate ? path.join(dir, candidate) : null
}

function chooseState(states) {
  const names = Object.keys(states)
  for (const preferred of PICK) {
    const hit = names.find((n) => n === preferred)
    if (hit) return hit
  }
  const substantive = names.find(
    (n) => !/loading|error|empty|skeleton|first-run|pending|offline/i.test(n),
  )
  return substantive ?? names[0]
}

let previewHandle = null

/* P7.1: `startPreview` spawns vite directly, so `stop()` reaches the process
   holding the port. The `npx` form leaked a server on every run. */
function serveDist() {
  previewHandle = startPreview(PORT, path.join(repoRoot, "web"))
  return previewHandle.child
}

async function waitForServer(server, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    // The D6.10 rule: never measure a server this process did not start.
    if (server.exitCode !== null) {
      throw new Error(
        `vite preview exited (code ${server.exitCode}) before answering on ${BASE}. ` +
          `Something else is holding port ${PORT}; this run will NOT capture a build ` +
          `it did not make.\n${previewHandle?.log() ?? ""}`,
      )
    }
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(2000) })
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`vite preview did not answer on ${BASE}\n${previewHandle?.log() ?? ""}`)
}

async function main() {
  fs.mkdirSync(path.join(OUT, "after"), { recursive: true })
  fs.mkdirSync(path.join(OUT, "before"), { recursive: true })

  // Before the spawn, where there is no race to lose. See serve_guard.mjs.
  await assertPortFree(BASE, PORT, "the gallery")

  const server = serveDist()
  const manifest = []
  try {
    await waitForServer(server)
    const browser = await chromium.launch()

    for (const pair of PAIRS) {
      const surface = SURFACES[pair.surface]
      if (!surface) throw new Error(`unknown surface "${pair.surface}"`)
      const stateName = chooseState(surface.states)
      const state = surface.states[stateName]
      const entry = { ...pair, state: stateName, after: {}, beforeFiles: {} }

      for (const vp of WIDTHS) {
        const session = surface.session === null ? null : { ...SESSION, ...(surface.session ?? {}) }
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          deviceScaleFactor: 1,
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
        await page.waitForTimeout(1100)
        if (surface.act) await surface.act(page, state)
        await page.waitForTimeout(300)

        const file = `${pair.surface}--${vp.name}.png`
        await page.screenshot({ path: path.join(OUT, "after", file), fullPage: true })
        entry.after[vp.name] = `after/${file}`
        await context.close()
      }

      // "Before" is copied rather than re-rendered; see the header.
      if (pair.before) {
        for (const key of ["1440", "380"]) {
          const from = beforeFile(pair.before, key)
          if (from) {
            const to = `${pair.surface}--${key}.png`
            fs.copyFileSync(from, path.join(OUT, "before", to))
            entry.beforeFiles[key] = `before/${to}`
          }
        }
      }

      manifest.push(entry)
      process.stdout.write(
        `. ${pair.surface} (${stateName})${pair.before ? "" : "  [new, no before]"}\n`,
      )
    }
    await browser.close()
  } finally {
    previewHandle?.stop()
  }

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2), "utf8")
  fs.writeFileSync(path.join(OUT, "index.html"), renderGallery(manifest), "utf8")

  const withBefore = manifest.filter((m) => m.beforeFiles["1440"]).length
  const missing = manifest.filter((m) => m.before && !m.beforeFiles["1440"])
  console.log(`\n${manifest.length} surfaces captured; ${withBefore} have a before pair.`)
  if (missing.length) {
    // Never silent: a surface whose "before" was expected and not found is a
    // gap in the gallery, not a surface that had no past.
    console.log(`MISSING before for: ${missing.map((m) => `${m.surface} (${m.before})`).join(", ")}`)
  }
  console.log(`wrote ${path.relative(repoRoot, path.join(OUT, "index.html"))}`)
}

function esc(text) {
  return String(text).replace(/[&<>"]/g, (c) => `&${{ "&": "amp", "<": "lt", ">": "gt", '"': "quot" }[c]};`)
}

export function renderGallery(manifest) {
  const rows = manifest
    .map((m) => {
      const before1440 = m.beforeFiles["1440"]
        ? `<figure><img src="${m.beforeFiles["1440"]}" alt="${esc(m.title)} before the redesign, desktop"><figcaption>before &middot; 1440</figcaption></figure>`
        : `<div class="none">no before &middot; this screen did not exist</div>`
      const before380 = m.beforeFiles["380"]
        ? `<figure><img src="${m.beforeFiles["380"]}" alt="${esc(m.title)} before the redesign, mobile"><figcaption>before &middot; 380</figcaption></figure>`
        : `<div class="none">no before</div>`
      return `<section>
  <h2>${esc(m.title)}</h2>
  <p class="meta">${esc(m.surface)} &middot; state <code>${esc(m.state)}</code>${m.before ? ` &middot; was <code>${esc(m.before)}</code>` : " &middot; new in the redesign"}</p>
  <div class="grid">
    ${before1440}
    <figure><img src="${m.after["1440"]}" alt="${esc(m.title)} after the redesign, desktop"><figcaption>after &middot; 1440</figcaption></figure>
    ${before380}
    <figure><img src="${m.after["375"]}" alt="${esc(m.title)} after the redesign, mobile"><figcaption>after &middot; 375</figcaption></figure>
  </div>
</section>`
    })
    .join("\n")

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lemely redesign — before and after</title>
<style>
  body { margin: 0; padding: 40px; background: #F7F6F3; color: #2F3437;
         font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.6; }
  header { max-width: 70ch; margin: 0 auto 56px; }
  h1 { font-family: ui-serif, Georgia, serif; font-weight: 600; font-size: 40px;
       line-height: 1.1; margin: 0 0 16px; }
  .note { color: #787774; font-size: 15px; }
  section { max-width: 1400px; margin: 0 auto 64px; padding-top: 32px;
            border-top: 1px solid #EAEAEA; }
  h2 { font-family: ui-serif, Georgia, serif; font-weight: 600; font-size: 26px; margin: 0; }
  .meta { color: #787774; font-size: 14px; margin: 4px 0 20px; }
  code { font-family: ui-monospace, monospace; font-size: 13px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
  figure { margin: 0; }
  img { width: 100%; height: auto; display: block; border: 1px solid #EAEAEA; border-radius: 8px; background: #fff; }
  figcaption { color: #787774; font-size: 13px; margin-top: 8px; }
  .none { color: #787774; font-size: 14px; border: 1px dashed #EAEAEA; border-radius: 8px;
          padding: 24px; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Lemely, before and after</h1>
  <p class="note">Left column is the build-era product, captured 2026-08-12 from
  <code>reports/phase-6/screens/</code>, the day before the redesign opened. Right column is
  this branch. The desktop pair is 1440 on both sides; the mobile pair is <strong>380 before
  and 375 after</strong>, because that is the width the build-era harness used, and relabelling
  it would be tidier than it is true. Every "after" is the fullest state of that surface, named
  under each heading, so a populated screen is never compared against an empty one.</p>
</header>
${rows}
</body>
</html>
`
}

/* Only when run directly. Importable so the HTML can be regenerated from an
   existing manifest without re-capturing 70 screenshots to produce identical
   files — which is how the S-14 pairing gap was closed. */
if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error)
    process.exitCode = 1
  })
}
