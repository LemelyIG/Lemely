/*
 * Writes `public/brand/mark.svg` and `public/brand/mark-mono.svg` from
 * `src/lib/brandMark.ts`.
 *
 * ── Why the files are generated ────────────────────────────────────────────
 *
 * The mark now ships in two renderers that cannot share code: an inline React
 * component (`components/ui/brand-mark.tsx`, the only one that animates) and
 * standalone SVG files (the favicon `<link>`, and the source `npm run icons`
 * rasterises the PWA icons and the OG card from). The usual arrangement is to
 * author the SVG by hand and transcribe it into the component under a "keep in
 * sync" comment on both. This repo has found that defect often enough to know
 * what such a comment is worth: it is a rule with no reader, and the two
 * diverge the first time somebody nudges a curve in one of them.
 *
 * So neither owns a coordinate. `lib/brandMark.ts` does, and this writes the
 * files. Same argument `generate_icons.mjs` makes about the PNGs and
 * `vite/brandTokens.ts` makes about the manifest colours, one level up.
 *
 * ── Why the colours are resolved rather than written ───────────────────────
 *
 * The geometry module names DESIGN.md tokens, not values. The component emits
 * them as `var(--ink)` and follows a token change with no edit. A standalone
 * SVG has no `:root` to resolve against, so this substitutes the value — but
 * through `tokenHex`, which reads the oklch declaration out of index.css and
 * converts it, rather than by transcribing a hex here. The old hand-authored
 * mark carried five literal colours and a comment asking the next editor to
 * keep them in step with DESIGN.md. This removes the ask.
 *
 * Run: `npm run mark` (or `npm run icons`, which runs this first).
 */

import { writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import {
  COIL,
  LEFT_FACE,
  MARK_MIRROR,
  MARK_TILT,
  MARK_VIEW_BOX,
  RIGHT_FACE,
  STACK_EDGES,
} from "../src/lib/brandMark.ts"
import { tokenHex } from "../vite/brandTokens.ts"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const BRAND = path.resolve(HERE, "../public/brand")

/*
 * The one-colour cut thins its ruling and nothing else.
 *
 * In the colour cut the ruling is `rule-strong` — a pale grey four steps off
 * the paper — so hue keeps it behind the sheet it is written on. Recoloured to
 * the foreground it becomes a full-strength line, and six of them at 0.95 would
 * out-shout the page. Everything else keeps its width, because with one hue the
 * RATIO between the widths is the entire design: ruling, margin, stack edge,
 * sheet, coil, tick, lightest to heaviest.
 */
const MONO_WIDTH = { "rule-strong": 0.7 }

function render(paths, { mono }) {
  return paths
    .map(({ d, fill, stroke, width }) => {
      const attrs = mono
        ? [`fill="none"`, `stroke="currentColor"`, `stroke-width="${MONO_WIDTH[stroke] ?? width}"`]
        : [
            `fill="${fill === "none" ? "none" : tokenHex(fill)}"`,
            `stroke="${stroke === "none" ? "none" : tokenHex(stroke)}"`,
            `stroke-width="${width}"`,
          ]
      const compact = d.replace(/\s+/g, " ").trim()
      return `    <path d="${compact}"\n          ${attrs.join(" ")} />`
    })
    .join("\n")
}

function document_(comment, { mono }) {
  const group = (paths, indent = "") => render(paths, { mono }).replace(/^/gm, indent)
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="${MARK_VIEW_BOX}" width="64" height="64"
     role="img" aria-label="Lemely">
  <title>Lemely</title>
  <!--
${comment}
  -->
  <g transform="${MARK_TILT}" stroke-linecap="round" stroke-linejoin="round">
    <!-- The block of sheets under each page, drawn as the two edges of it that
         show. Depth by offset and tone, never by shadow (DESIGN.md §7). -->
    <g transform="${MARK_MIRROR}">
${group(STACK_EDGES, "  ")}
    </g>
${group(STACK_EDGES)}

    <!-- The left page: the sheet already turned, and marked. Right-half
         geometry mirrored about the spine, which is why its tick is authored
         backwards. -->
    <g transform="${MARK_MIRROR}">
${group(LEFT_FACE, "  ")}
    </g>

    <!-- The right page: work, unmarked, dog-eared at its outer corner. -->
${group(RIGHT_FACE)}

    <!-- The coil, over both pages, because it wraps over them. -->
${group(COIL)}
  </g>
</svg>
`
}

const SHARED = `    GENERATED FILE. Do not edit by hand — \`npm run mark\` overwrites it.
    The coordinates live in \`src/lib/brandMark.ts\`; the colours are resolved
    from the oklch tokens in \`src/index.css\` by \`vite/brandTokens.ts\`.`

const COLOUR_COMMENT = `    Lemely mark: an open spiral notebook, drawn by hand.

${SHARED}

    ── The idea ───────────────────────────────────────────────────────────────

    The previous mark was concept a3 from BUILD/BRAND.md §3: a printed hairline
    L — a margin rule meeting a baseline — with a heavy accent tick laid across
    it. That idea survives here. The margin is still drawn, the tick is still
    the heaviest stroke in the mark and still the one thing a hand made; what
    has changed is that the page they are on is now the artefact itself instead
    of two lines implying it. BRAND.md §2 lists the margin, the tick, the ruled
    line, the stacked sheet and the dog-ear all in territory; this is those five
    resolved into one object, and the hard bans in §2 are untouched — no cap, no
    open book of the graduation-clipart kind, no lightbulb, no sparkle, no
    swoosh.

    The notebook is open, and that is load-bearing rather than decorative. It
    gives the mark a left page and a right page: work on the right, unmarked;
    the same sheet on the left, turned over, carrying the tick. The mark is not
    an ornament sitting on the drawing, it is the state a page arrives in once
    it has been through the product. It is also what lets the inline cut animate
    — a page turn needs somewhere to land, and a closed notebook has nowhere.

    ── Why this file does not animate ─────────────────────────────────────────

    The mark riffles its pages. That happens in
    \`src/components/ui/brand-mark.tsx\`, which draws this same geometry inline,
    and it happens there rather than here for a measured reason.

    An SVG referenced by \`<img>\` is a separate document. It runs no script, and
    the host page's CSS — including index.css's global
    \`prefers-reduced-motion: reduce\` block, which flattens every animation in
    the product — cannot reach it. Carrying the media query inside this file
    instead does not work either: Chromium does not propagate the preference
    into an SVG-as-image at all. Measured directly, with a probe SVG whose fill
    changes under the query and an \`<img>\` on a page whose own
    \`matchMedia("(prefers-reduced-motion: reduce)")\` returns true — the image
    rendered the no-preference branch in both states.

    So an animated \`mark.svg\` would move in every header of the product for a
    reader who had asked it not to, with a reassuring-looking media query
    sitting in the file appearing to prevent it. That is the exact shape of
    defect this build keeps finding, and it is not worth shipping for the
    convenience of an \`<img>\` tag.

    This file therefore stays still, and stays the source for everything that
    cannot render a React component: the favicon \`<link>\` in index.html, and the
    PWA icons and OG card that \`npm run icons\` rasterises from it.

    One note for editors: this comment sits INSIDE the svg element on purpose.
    libvips (and so sharp, and so the screenshot tooling) sniffs only the first
    bytes of a file to detect SVG; a long leading comment pushes the opening tag
    out of that window and the file is rejected as an unknown format. Keep the
    opening tag at the top.`

const MONO_COMMENT = `    Lemely mark, single-colour cut.

${SHARED}

    For anywhere the accent cannot be relied on: one-colour print, an embossed
    or engraved application, a foreground-colour context, or a surface where the
    warm red would clash. \`currentColor\` throughout, so in HTML it inherits the
    surrounding text colour and needs no variant per background.

    Same geometry as mark.svg, coordinate for coordinate, with two differences
    the generator applies:

    - No fills. A one-colour mark has to work on a surface whose colour it does
      not know, so it cannot paint its own paper; and filling the pages in
      currentColor would weld the stack into one blob. Nothing is lost, because
      this drawing hides nothing behind a fill: the backing sheets are already
      only the edges of themselves, and the coil is drawn over the pages rather
      than through them.

    - The ruling is thinner. It is \`rule-strong\` in the colour cut — pale grey,
      held back by hue — and recolouring it to the foreground makes it a
      full-strength line. Everything else keeps its width, because with one hue
      the ratio between the widths is the entire design.

    Keep the opening tag at the top: libvips sniffs only the first bytes of a
    file to detect SVG, and a long leading comment would push it out of range.`

for (const [file, comment, opts] of [
  ["mark.svg", COLOUR_COMMENT, { mono: false }],
  ["mark-mono.svg", MONO_COMMENT, { mono: true }],
]) {
  writeFileSync(path.join(BRAND, file), document_(comment, opts))
  console.log(`brand/${file}  ${opts.mono ? "currentColor" : "tokens resolved to hex"}`)
}
