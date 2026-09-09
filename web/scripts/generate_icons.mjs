/*
 * Regenerates the PWA / home-screen PNG icons from the real brand mark.
 *
 * ── Why this exists (P6.5) ──────────────────────────────────────────────────
 *
 * REDESIGN-MISSION §5 Phase 6.5 asks for "favicon (new logo)". The finding
 * underneath that one line is larger than it sounds: **the browser tab was the
 * one surface the redesign never reached.** `public/favicon.svg` was the
 * build-era mark — a `#863bff` purple glyph — and §4 names "purple-blue
 * gradients" as this redesign's hard anti-reference, so the single most-seen
 * piece of Lemely's identity was painted in the one colour family the mission
 * bans outright. The three PNG icons beside it were rasterised from that same
 * purple mark on 2026-08-12, i.e. before Phase 2 existed.
 *
 * Nothing could have caught it. Every gate this build runs reads code or reads
 * a rendered page; an icon is a binary that no test opens, displayed by an
 * operating system in a place no screenshot harness captures. It is the same
 * shape as D6.4's `registerSW.js` (in nobody's diff) and this phase's manifest
 * colour (read by an OS, not by a test).
 *
 * ── Why a checked-in script rather than four checked-in binaries ────────────
 *
 * The binaries are checked in too — they have to be, they are served — but a
 * PNG in a diff is unreviewable, and "regenerate the icons" is otherwise a
 * piece of knowledge that lives in one person's head until it is lost. This
 * makes the mark the source and the PNGs the artifact, which is the same
 * argument `vite/brandTokens.ts` makes about the manifest colours.
 *
 * Run: `npm run icons`
 *
 * ── The maskable cut is a different image, not a resize ─────────────────────
 *
 * Android crops a maskable icon to whatever shape the launcher wants (circle,
 * squircle, teardrop), guaranteeing only the central 80% *diameter*. A mark
 * sized for the square icon loses its corners in that crop. So the maskable
 * variant paints the same mark smaller, inside the safe circle, on a full-bleed
 * paper field. Verified arithmetically below rather than by eye.
 */

import { readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import sharp from "sharp"
import { tokenHex } from "../vite/brandTokens.ts"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PUBLIC = path.resolve(HERE, "../public")

/** The vector the whole identity comes from. */
const MARK = path.join(PUBLIC, "brand/mark.svg")

/*
 * The canvas colour, read from `--paper` rather than transcribed. An icon sits
 * against the OS's own background, so it needs an opaque field of its own; the
 * product's page colour is the honest choice, and `brandTokens` means it cannot
 * drift from the page the icon opens into.
 */
const PAPER = tokenHex("paper")

/**
 * How much of the icon's width the mark's ARTBOARD spans.
 *
 * Both figures moved when the mark became an open notebook. The old mark was a
 * tall glyph using about 42% of its artboard's width, so 0.62 here left it
 * genuinely small on a home screen; the notebook is landscape and nearly fills
 * its artboard across, so the same number would have shrunk it further.
 *
 * `0.72` for the square cuts, which puts the drawn mark at about 64% of the
 * icon's width and 49% of its height — a normal figure for an app icon, and one
 * that still leaves the outer edge clear on a rounded-rectangle mask.
 *
 * `0.60` for maskable, against a measured ceiling of 0.71 (see below). The
 * margin is for the launcher shapes that crop harder than a circle.
 */
const SQUARE_SCALE = 0.72
const MASKABLE_SCALE = 0.6

const ICONS = [
  { file: "pwa-192x192.png", size: 192, scale: SQUARE_SCALE },
  { file: "pwa-512x512.png", size: 512, scale: SQUARE_SCALE },
  { file: "maskable-icon-512x512.png", size: 512, scale: MASKABLE_SCALE },
]

const markSvg = readFileSync(MARK)

/**
 * The mark's drawn extent, as a fraction of its artboard, measured from the
 * rendered alpha rather than read off the coordinates.
 *
 * The safe-zone arithmetic below needs this, and the previous version of this
 * file assumed the artboard was filled edge to edge. That was conservative for
 * the old mark and it is conservative for this one — but conservative by an
 * unknown amount, which is the same thing as not knowing. An open notebook is
 * two thirds as tall as it is wide, and a bound derived from a square it does
 * not occupy would have kept the maskable icon a third smaller than it needs to
 * be for no stated reason.
 */
async function drawnExtent() {
  const N = 512
  const { data } = await sharp(markSvg, { density: 384 })
    .resize(N, N)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  let left = N
  let top = N
  let right = -1
  let bottom = -1
  for (let y = 0; y < N; y += 1) {
    for (let x = 0; x < N; x += 1) {
      // 8/255, so a stroke's outermost antialiased fringe does not count as ink.
      if (data[(y * N + x) * 4 + 3] <= 8) continue
      if (x < left) left = x
      if (x > right) right = x
      if (y < top) top = y
      if (y > bottom) bottom = y
    }
  }
  return { width: (right - left + 1) / N, height: (bottom - top + 1) / N }
}

/*
 * Guard the safe-zone arithmetic in the file that depends on it, so a future
 * edit to MASKABLE_SCALE — or to the mark's own proportions — cannot quietly
 * push it under an Android crop. Nothing else in the repo checks this: it runs
 * here because here is where someone editing the number is actually looking.
 *
 * Android crops a maskable icon to whatever shape the launcher wants and
 * guarantees only the central circle of diameter 0.8w. A rectangle of w x h
 * (as fractions of the icon) is fully inside it only when its diagonal fits,
 * i.e. hypot(w, h) <= 0.8.
 */
const EXTENT = await drawnExtent()
const MAX_MASKABLE_SCALE =
  0.8 / Math.hypot(EXTENT.width, EXTENT.height)
if (MASKABLE_SCALE > MAX_MASKABLE_SCALE) {
  throw new Error(
    `generate_icons: MASKABLE_SCALE ${MASKABLE_SCALE} exceeds ${MAX_MASKABLE_SCALE.toFixed(3)} ` +
      `for a mark drawn ${EXTENT.width.toFixed(3)} x ${EXTENT.height.toFixed(3)} of its artboard, ` +
      "so its corners fall outside Android's guaranteed-visible circle and will be cropped.",
  )
}

/*
 * The Open Graph card (P6.5), 1200x630 as every scraper expects.
 *
 * **It carries no text, deliberately.** The obvious card sets "Lemely" in
 * Newsreader beside the mark — and it cannot be built here honestly. @fontsource
 * ships woff2 only, which librvsg (and so sharp) cannot load, so an SVG asking
 * for `font-family: Newsreader` would silently render in whatever fontconfig
 * picks, most likely DejaVu Sans. §3.2 item 2 bans Arial-class defaults
 * outright, and a wrong face in a generated binary is invisible to every gate
 * in this repo: nobody diffs a PNG, and the file only ever renders inside
 * somebody else's chat app.
 *
 * So the card is the mark on paper with the ruled motif, and the product's name
 * is carried by `og:title`, which is real text in the scraper's own typography.
 * That is a smaller card than a wordmark lockup would be, and it is one that
 * cannot quietly be wrong.
 */
const OG = { file: "brand/og-card.png", width: 1200, height: 630 }

const ogRules = `<svg xmlns="http://www.w3.org/2000/svg" width="${OG.width}" height="${OG.height}">
  <g stroke="${tokenHex("rule")}" stroke-width="1.5">
    ${[...Array(7)].map((_, i) => `<path d="M0 ${95 + i * 72}H${OG.width}" />`).join("\n    ")}
  </g>
</svg>`

const ogMark = await sharp(markSvg, { density: 384 }).resize(300, 300).png().toBuffer()
const ogCard = await sharp({
  create: { width: OG.width, height: OG.height, channels: 4, background: PAPER },
})
  .composite([
    { input: Buffer.from(ogRules), gravity: "northwest" },
    { input: ogMark, gravity: "centre" },
  ])
  .png({ compressionLevel: 9 })
  .toBuffer()
writeFileSync(path.join(PUBLIC, OG.file), ogCard)
console.log(`${OG.file}  ${OG.width}x${OG.height}  mark 300px on ${PAPER}, no text (see comment)`)

for (const { file, size, scale } of ICONS) {
  // Render the vector at its final pixel size rather than rasterising once and
  // resampling: the mark is two hairlines and a stroke, and a downsampled
  // hairline turns grey.
  const markPx = Math.round(size * scale)
  const mark = await sharp(markSvg, { density: 384 }).resize(markPx, markPx).png().toBuffer()

  const out = await sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: PAPER,
    },
  })
    .composite([{ input: mark, gravity: "centre" }])
    .png({ compressionLevel: 9 })
    .toBuffer()

  writeFileSync(path.join(PUBLIC, file), out)
  console.log(`${file}  ${size}x${size}  mark ${markPx}px on ${PAPER}`)
}
