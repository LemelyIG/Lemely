#!/usr/bin/env node
/**
 * Per-role contact sheets (P6.7).
 *
 * MISSION §4 (Phase 6) asks for a **per-role** contact sheet as part of the
 * full-product visual QA sweep. `web/scripts/audit.mjs` already writes one
 * flat `contact-sheet.html` covering every screen it captured, which is the
 * right artifact for "did the corpus build" but the wrong one for the job
 * MISSION describes: the human is reviewing this remotely from a phone, and
 * "show me every teacher screen" is the question they actually ask. A single
 * 44-screen scroll answers it slowly.
 *
 * This is a separate script rather than an edit to `audit.mjs` on purpose.
 * That file is the run that produces the evidence and it was stabilised at
 * P6.1; a presentation concern does not belong inside it, and keeping them
 * apart means the sheets can be regenerated from a committed corpus without
 * re-running an 11-minute audit. It reads only what is on disk.
 *
 * Roles come from the screen-id prefix in `docs/LEMELY_UI_SPEC.md`:
 *   S-xx student · T-xx teacher · P-xx parent · G-xx cross-role.
 * `G-` is its own sheet rather than being duplicated into the other three:
 * login, settings and the device screen are genuinely shared surfaces, and
 * copying them into every role's sheet would overstate the corpus size in
 * three places at once. **An id matching no prefix lands in "Unclassified"
 * rather than being dropped** — a screen missing from a sheet reads as a
 * screen that was never captured, which is the one failure mode a contact
 * sheet exists to prevent.
 *
 * Usage:  LEMELY_REPORT_DIR=reports/phase-6 node scripts/contact_sheets.mjs
 * Writes: <report-dir>/contact-sheet-<role>.html and -index.html
 */

import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(__dirname, "..")
const repoRoot = path.resolve(webRoot, "..")

const REPORT_DIR_SETTING = process.env.LEMELY_REPORT_DIR || "reports/.scratch"
const REPORTS_DIR = path.isAbsolute(REPORT_DIR_SETTING)
  ? REPORT_DIR_SETTING
  : path.resolve(repoRoot, REPORT_DIR_SETTING)
const SCREENS_DIR = path.join(REPORTS_DIR, "screens")

const ROLES = [
  { key: "student", label: "Student", prefix: "S-" },
  { key: "teacher", label: "Teacher", prefix: "T-" },
  { key: "parent", label: "Parent", prefix: "P-" },
  { key: "shared", label: "Shared (all roles)", prefix: "G-" },
]
const UNCLASSIFIED = { key: "unclassified", label: "Unclassified", prefix: null }

const STYLE = `
  :root { color-scheme: light; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 24px 32px 64px; background: #faf4f2; color: #1e1310; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .meta { color: #6b5b54; font-size: 13px; margin-bottom: 8px; }
  nav { margin: 16px 0 32px; font-size: 13px; }
  nav a { color: #1e1310; margin-right: 16px; }
  h2 { font-size: 16px; border-bottom: 1px solid #e3d5cf; padding-bottom: 6px; margin-top: 40px; }
  .count { font-weight: 400; color: #9a877d; font-size: 13px; }
  .grid { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; }
  figure.thumb { margin: 0; width: 220px; }
  figure.thumb img { width: 100%; height: auto; border: 1px solid #e3d5cf; border-radius: 6px; display: block; background: #fff; }
  figcaption { font-size: 11.5px; color: #6b5b54; margin-top: 4px; word-break: break-all; text-align: center; }
  ul.roles { font-size: 14px; line-height: 1.9; padding-left: 18px; }
`

/** Every screen-id directory that actually holds at least one PNG. */
function readCorpus() {
  if (!fs.existsSync(SCREENS_DIR)) return []
  return fs
    .readdirSync(SCREENS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => ({
      screenId: d.name,
      files: fs
        .readdirSync(path.join(SCREENS_DIR, d.name))
        .filter((f) => f.endsWith(".png"))
        .sort(),
    }))
    .filter((s) => s.files.length > 0)
    .sort((a, b) => a.screenId.localeCompare(b.screenId))
}

function roleOf(screenId) {
  return ROLES.find((r) => screenId.startsWith(r.prefix)) ?? UNCLASSIFIED
}

function section({ screenId, files }) {
  const thumbs = files
    .map((f) => {
      const label = f.replace(/\.png$/, "")
      const src = `screens/${screenId}/${f}`
      return `
        <figure class="thumb">
          <a href="${src}" target="_blank" rel="noopener noreferrer">
            <img src="${src}" alt="${screenId} — ${label}" loading="lazy" />
          </a>
          <figcaption>${label}</figcaption>
        </figure>`
    })
    .join("\n")
  return `
    <section class="screen">
      <h2 id="${screenId}">${screenId} <span class="count">(${files.length})</span></h2>
      <div class="grid">${thumbs}
      </div>
    </section>`
}

function page(title, meta, nav, body) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${title}</title>
<style>${STYLE}</style>
</head>
<body>
  <h1>${title}</h1>
  <p class="meta">${meta}</p>
  ${nav}
  ${body}
</body>
</html>
`
}

function main() {
  const corpus = readCorpus()
  if (corpus.length === 0) {
    // Loud, not silent: an empty corpus means the audit did not run or wrote
    // somewhere else, and a cheerful set of empty sheets would hide that.
    console.error(`[contact-sheets] no screenshots under ${SCREENS_DIR} — nothing to do`)
    process.exitCode = 1
    return
  }

  const generated = new Date().toISOString()
  const buckets = [...ROLES, UNCLASSIFIED].map((role) => ({
    role,
    screens: corpus.filter((s) => roleOf(s.screenId).key === role.key),
  }))
  // An empty role is dropped from the output but still reported on the index,
  // so "the parent sheet is missing" and "the parent has no screens" stay
  // distinguishable.
  const present = buckets.filter((b) => b.screens.length > 0)

  const navLinks = [`<a href="contact-sheet-index.html">Index</a>`]
    .concat(present.map((b) => `<a href="contact-sheet-${b.role.key}.html">${b.role.label}</a>`))
    .join("")
  const nav = `<nav>${navLinks}</nav>`

  for (const b of present) {
    const shots = b.screens.reduce((n, s) => n + s.files.length, 0)
    fs.writeFileSync(
      path.join(REPORTS_DIR, `contact-sheet-${b.role.key}.html`),
      page(
        `Lemely — ${b.role.label} contact sheet`,
        `Generated ${generated} from ${path.relative(repoRoot, SCREENS_DIR)}/. ` +
          `${b.screens.length} screen(s), ${shots} screenshot(s).`,
        nav,
        b.screens.map(section).join("\n"),
      ),
    )
  }

  const totalShots = corpus.reduce((n, s) => n + s.files.length, 0)
  const rows = buckets
    .map(
      (b) =>
        `<li><strong>${b.role.label}</strong> — ${b.screens.length} screen(s), ` +
        `${b.screens.reduce((n, s) => n + s.files.length, 0)} screenshot(s)` +
        (b.screens.length
          ? ` · <a href="contact-sheet-${b.role.key}.html">open</a>`
          : ` · <em>no screens</em>`) +
        `</li>`,
    )
    .join("\n")
  fs.writeFileSync(
    path.join(REPORTS_DIR, "contact-sheet-index.html"),
    page(
      "Lemely — visual QA contact sheets by role",
      `Generated ${generated} from ${path.relative(repoRoot, SCREENS_DIR)}/. ` +
        `${corpus.length} screen(s), ${totalShots} screenshot(s) in total. ` +
        `The flat all-screens sheet is <a href="contact-sheet.html">contact-sheet.html</a>.`,
      nav,
      `<ul class="roles">\n${rows}\n</ul>`,
    ),
  )

  console.log(
    `[contact-sheets] ${corpus.length} screens / ${totalShots} screenshots -> ` +
      present.map((b) => `${b.role.key}:${b.screens.length}`).join(" "),
  )
  if (buckets.at(-1).screens.length > 0) {
    console.log(
      `[contact-sheets] NOTE ${buckets.at(-1).screens.length} screen id(s) matched no ` +
        `S-/T-/P-/G- prefix and are on the Unclassified sheet: ` +
        buckets.at(-1).screens.map((s) => s.screenId).join(", "),
    )
  }
}

main()
