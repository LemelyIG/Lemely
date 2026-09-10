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
import { MASKABLE_SCALE, MAX_MASKABLE_SCALE, SQUARE_SCALE, tokenHex } from "../vite/brandTokens.ts"

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

/*
 * The icon-sizing constants (`SQUARE_SCALE`, `MASKABLE_SCALE`,
 * `MAX_MASKABLE_SCALE`) now live in `vite/brandTokens.ts` (packet A5), so
 * this script and `tests/unit/brandTokens.test.ts` share one definition
 * apiece rather than a transcription each could drift from.
 */
const ICONS = [
  { file: "pwa-192x192.png", size: 192, scale: SQUARE_SCALE },
  { file: "pwa-512x512.png", size: 512, scale: SQUARE_SCALE },
  { file: "maskable-icon-512x512.png", size: 512, scale: MASKABLE_SCALE },
  // packet A5 (`apple-touch-icon-reuses-192`): a real 180px cut for iOS's own
  // home-screen icon, rather than `index.html` pointing an
  // `apple-touch-icon` link at the 192px PWA icon and letting iOS downsample
  // it itself.
  { file: "apple-touch-icon.png", size: 180, scale: SQUARE_SCALE },
  // packet A5 (`no-1024-store-icon`): the 1024px listing icon some install
  // surfaces (and app-store-style listings) expect. `alpha: false` because a
  // store icon must be fully opaque with no alpha channel at all — some
  // validators reject one even when every pixel happens to be opaque.
  { file: "store-icon-1024.png", size: 1024, scale: SQUARE_SCALE, alpha: false },
  // packet A5 (`manifest-shortcuts`): the three manifest `shortcuts` entries
  // (`vite/manifest.ts`) need an icon apiece. Same mark-on-paper treatment as
  // the square PWA icons for now — these are jump-list glyphs, not full
  // screenshots, so one shared look is correct rather than three bespoke cuts.
  { file: "shortcut-mark-96.png", size: 96, scale: SQUARE_SCALE },
  { file: "shortcut-dashboard-96.png", size: 96, scale: SQUARE_SCALE },
  { file: "shortcut-notifications-96.png", size: 96, scale: SQUARE_SCALE },
]

/*
 * Guard the safe-zone arithmetic in the file that depends on it, so a future
 * edit to MASKABLE_SCALE cannot quietly push the mark under an Android crop.
 * `tests/unit/brandTokens.test.ts` asserts the same bound; this is the belt to
 * its braces, and it runs in the one place someone editing the number is
 * actually looking.
 */
if (MASKABLE_SCALE > MAX_MASKABLE_SCALE) {
  throw new Error(
    `generate_icons: MASKABLE_SCALE ${MASKABLE_SCALE} exceeds ${MAX_MASKABLE_SCALE.toFixed(3)}, ` +
      "so the mark's corners fall outside Android's guaranteed-visible circle and will be cropped.",
  )
}

const markSvg = readFileSync(MARK)

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

/**
 * Wraps a PNG buffer in a minimal single-image ICO container.
 *
 * ICO has allowed an embedded PNG directly (no BMP re-encoding) since Vista —
 * an `ICONDIRENTRY` whose image data starts with the PNG magic bytes is a
 * PNG, full stop. So this needs no image-format dependency beyond the PNG
 * `sharp` already produces: a 6-byte `ICONDIR` header, one 16-byte
 * `ICONDIRENTRY`, then the PNG bytes verbatim.
 */
function pngToIco(png, size) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: 1 = icon
  header.writeUInt16LE(1, 4) // one image

  const entry = Buffer.alloc(16)
  // Width/height: 0 means "256"; this repo's favicon is always <256, so the
  // literal size is always the correct byte.
  entry.writeUInt8(size, 0)
  entry.writeUInt8(size, 1)
  entry.writeUInt8(0, 2) // colour count: 0 = not palette-indexed
  entry.writeUInt8(0, 3) // reserved
  entry.writeUInt16LE(1, 4) // colour planes
  entry.writeUInt16LE(32, 6) // bits per pixel (RGBA)
  entry.writeUInt32LE(png.length, 8) // image data size
  entry.writeUInt32LE(header.length + entry.length, 12) // offset to image data

  return Buffer.concat([header, entry, png])
}

for (const { file, size, scale, alpha } of ICONS) {
  // Render the vector at its final pixel size rather than rasterising once and
  // resampling: the mark is two hairlines and a stroke, and a downsampled
  // hairline turns grey.
  const markPx = Math.round(size * scale)
  const mark = await sharp(markSvg, { density: 384 }).resize(markPx, markPx).png().toBuffer()

  let pipeline = sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: PAPER,
    },
  }).composite([{ input: mark, gravity: "centre" }])
  // `alpha: false` (the store-listing icon): drop the alpha channel entirely
  // rather than relying on every pixel already being opaque — some store
  // validators reject a PNG that carries an alpha channel at all.
  if (alpha === false) pipeline = pipeline.removeAlpha()

  const out = await pipeline.png({ compressionLevel: 9 }).toBuffer()

  writeFileSync(path.join(PUBLIC, file), out)
  console.log(`${file}  ${size}x${size}  mark ${markPx}px on ${PAPER}${alpha === false ? "  (no alpha)" : ""}`)
}

/*
 * packet A5 (`no-favicon-ico-fallback`): a real `favicon.ico` alongside the
 * SVG favicon `index.html` already links. Firefox reader mode, RSS readers
 * and other UAs that never look at `<link rel="icon">` still fall back to
 * `/favicon.ico` by convention — see `pngToIco`'s own docstring for why this
 * needs no new dependency.
 */
const FAVICON_SIZE = 32
const faviconMarkPx = Math.round(FAVICON_SIZE * SQUARE_SCALE)
const faviconMark = await sharp(markSvg, { density: 384 })
  .resize(faviconMarkPx, faviconMarkPx)
  .png()
  .toBuffer()
const faviconPng = await sharp({
  create: { width: FAVICON_SIZE, height: FAVICON_SIZE, channels: 4, background: PAPER },
})
  .composite([{ input: faviconMark, gravity: "centre" }])
  .png({ compressionLevel: 9 })
  .toBuffer()
const faviconIco = pngToIco(faviconPng, FAVICON_SIZE)
writeFileSync(path.join(PUBLIC, "favicon.ico"), faviconIco)
console.log(`favicon.ico  ${FAVICON_SIZE}x${FAVICON_SIZE}  mark ${faviconMarkPx}px on ${PAPER}`)
