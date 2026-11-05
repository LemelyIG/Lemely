/*
 * Writes `public/brand/mark.svg`, `public/brand/mark-favicon.svg` (the same
 * drawing under the name `index.html` links as the tab icon) and
 * `public/brand/mark-mono.svg`: the "lm"
 * icon from DESIGN.md's "Logo: Clip Letters" section.
 *
 * The icon is a rounded square (rx 24 of 100) in Abyss, a Tide paperclip (the
 * `l`, drawn with the logo's own path at stroke 5, round caps, no fill) and a
 * white `m`. It is the logo below its 20px minimum height, so it is what the
 * favicon, the PWA icons and the OG card are built from.
 *
 * ── Why the files are generated ────────────────────────────────────────────
 *
 * The geometry lives here once, and the colours are resolved from the token
 * layer in `src/index.css` through `vite/brandTokens.ts` rather than written
 * as hex, so the icon follows DESIGN.md. A standalone SVG has no `:root` to
 * resolve `var()` against, which is why the value is substituted.
 *
 *   tile  `--md-primary`          Abyss
 *   clip  `--md-inverse-primary`  Tide
 *   m     `--md-on-primary`       white
 *
 * The `m` is a stroked path rather than text: librsvg (and so sharp) cannot
 * load the Bricolage woff2, so a `<text>` element would fall back to whatever
 * fontconfig picks.
 *
 * The file declares no animation. An SVG referenced by `<img>` is a separate
 * document, so the global `prefers-reduced-motion` block cannot reach it.
 *
 * Run: `npm run mark` (or `npm run icons`, which runs this first).
 */

import { writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { tokenHex } from "../vite/brandTokens.ts"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const BRAND = path.resolve(HERE, "../public/brand")

/** DESIGN.md "Logo: Clip Letters": the paperclip, viewBox `28 4 46 94`. */
export const CLIP_PATH =
  "M58 34 V72 A8 8 0 0 1 42 72 V20 A14 14 0 0 1 70 20 V78 A18 18 0 0 1 34 78 V36"
const CLIP_STROKE = 5
/** The clip's drawn box is x 34..70, y 6..96; this places it left of the `m`. */
const CLIP_TRANSFORM = "translate(22 27.5) scale(0.5) translate(-34 -6)"
/** A geometric lowercase `m`: three stems joined by two arches. */
const M_PATH = "M49 72 V51 M49 58 A7 7 0 0 1 63 58 V72 M63 58 A7 7 0 0 1 77 58 V72"
const M_STROKE = 6.5

function glyphs({ clip, letter }) {
  return `  <path d="${CLIP_PATH}" transform="${CLIP_TRANSFORM}"
        fill="none" stroke="${clip}" stroke-width="${CLIP_STROKE}" stroke-linecap="round" stroke-linejoin="round" />
  <path d="${M_PATH}"
        fill="none" stroke="${letter}" stroke-width="${M_STROKE}" stroke-linecap="round" stroke-linejoin="round" />`
}

function document_(comment, body) {
  // The opening tag stays first: libvips sniffs only the first bytes of a file
  // to detect SVG, and a long leading comment would push it out of range.
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100"
     role="img" aria-label="Lemely">
  <title>Lemely</title>
  <!--
${comment}
  -->
${body}
</svg>
`
}

const SHARED = `    GENERATED FILE. Do not edit by hand: \`npm run mark\` overwrites it.
    The geometry lives in \`web/scripts/generate_mark_svg.mjs\`; the colours are
    resolved from the Material 3 role tokens in \`src/index.css\` by \`vite/brandTokens.ts\`.`

const COLOUR_COMMENT = `    Lemely "lm" icon (DESIGN.md, Logo: Clip Letters): Abyss tile, Tide clip, white m.

${SHARED}`

const MONO_COMMENT = `    Lemely "lm" icon, single-colour cut: the clip and the m in currentColor, no tile.

${SHARED}`

const colour = document_(
  COLOUR_COMMENT,
  `  <rect width="100" height="100" rx="24" fill="${tokenHex("md-primary")}" />
${glyphs({ clip: tokenHex("md-inverse-primary"), letter: tokenHex("md-on-primary") })}`,
)
const mono = document_(MONO_COMMENT, glyphs({ clip: "currentColor", letter: "currentColor" }))

for (const [file, svg, label] of [
  ["mark.svg", colour, "tokens resolved to hex"],
  ["mark-favicon.svg", colour, "tokens resolved to hex (tab icon)"],
  ["mark-mono.svg", mono, "currentColor"],
]) {
  writeFileSync(path.join(BRAND, file), svg)
  console.log(`brand/${file}  ${label}`)
}
