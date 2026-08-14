/*
 * Build-time access to the design tokens, read from the one file that defines
 * them.
 *
 * ── Why this exists (P6.5) ──────────────────────────────────────────────────
 *
 * Three files outside `index.css` need a token as a **literal hex string**,
 * because the consumer is not a browser applying CSS:
 *
 *   - the PWA manifest's `theme_color` and `background_color` (read by the OS
 *     to paint a splash screen and a task-switcher card),
 *   - `<meta name="theme-color">` in `index.html` (read by mobile browsers to
 *     tint their own chrome),
 *   - the generated PNG app icons (`scripts/generate_icons.mjs`).
 *
 * None of them can hold a `var()`. That is D5.1's finding in a third place: a
 * value handed to something that is not the CSS engine has to be resolved
 * first. The question this file answers is the one P6.4 left for P6.5 —
 * *what re-states a value, and what checks that the two still agree?*
 *
 * **They had already drifted, which is why this is a module and not a
 * comment.** `vite.config.ts` carried `theme_color: "#1e1310"` under a comment
 * claiming it was "computed from index.css's student/default theme tokens via
 * a real oklch->sRGB conversion (culori formatHex): --ink oklch(0.2 0.02 35)".
 * Every clause of that comment is now false. `--ink` is `oklch(0.321 0.009
 * 234)`, culori is not a dependency of this project and by the look of it never
 * was, and the hex is a build-era Material-3 brown that no token in the product
 * has produced since Phase 2 rewrote the palette. Nothing failed, because
 * nothing was checking: a manifest colour is read by an operating system, not
 * by a test.
 *
 * So the value is computed at build time from `index.css`, and the transcription
 * is deleted rather than corrected. A comment describing an intention is not
 * evidence the code has it — the fifth time this build has recorded that, and
 * the first time the evidence was a colour an OS paints where no reviewer looks.
 *
 * ── Why it throws ──────────────────────────────────────────────────────────
 *
 * Same reasoning as `fontPreload.ts`: the failure mode is silent. A renamed
 * token would leave the manifest with *some* colour, the build would succeed,
 * the app would install, and the splash screen would be the wrong colour on a
 * surface no gate in this repo can see. A missing token fails the build.
 */

import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** The token file. The only source; deliberately not a parameter. */
export const INDEX_CSS = path.resolve(HERE, "../src/index.css")

/**
 * Converts OKLCH to gamma-encoded sRGB in 0..1, clipping out of gamut.
 *
 * This is the same arithmetic as `tests/test_design_tokens.py::oklch_to_srgb`,
 * deliberately duplicated rather than shared, because the two live in different
 * languages and the Python one is the *contrast authority* for the whole
 * palette. `tests/unit/brandTokens.test.ts` pins this implementation against
 * values the Python computes, so a divergence between the two is a red test
 * rather than a slow disagreement — P6.4's whole lesson, where a hand
 * transcription let the authority measure one palette while the browser painted
 * another.
 *
 * D6.6 is the evidence that this formula is right rather than merely plausible:
 * Chromium was measured painting `--accent` at exactly the (192, 82, 60) this
 * computes, four independent ways.
 */
export function oklchToSrgb(lightness: number, chroma: number, hueDeg: number): [number, number, number] {
  const hue = (hueDeg * Math.PI) / 180
  const a = chroma * Math.cos(hue)
  const b = chroma * Math.sin(hue)

  // Long / medium / short cone responses, cubed back out of OKLab's cube root.
  const coneL = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const coneM = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const coneS = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3

  const linear: [number, number, number] = [
    4.0767416621 * coneL - 3.3077115913 * coneM + 0.2309699292 * coneS,
    -1.2684380046 * coneL + 2.6097574011 * coneM - 0.3413193965 * coneS,
    -0.0041960863 * coneL - 0.7034186147 * coneM + 1.707614701 * coneS,
  ]

  const encode = (value: number): number => {
    const clipped = Math.max(0, Math.min(1, value))
    return clipped > 0.0031308 ? 1.055 * clipped ** (1 / 2.4) - 0.055 : 12.92 * clipped
  }

  return [encode(linear[0]), encode(linear[1]), encode(linear[2])]
}

/** `#rrggbb`, lowercase. */
export function toHex(rgb: readonly [number, number, number]): string {
  return (
    "#" +
    rgb
      .map((channel) =>
        Math.round(channel * 255)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("")
  )
}

/**
 * Parses every `--name: oklch(L C H)` declaration out of `:root`.
 *
 * Scoped to `:root` on purpose. `index.css` also carries per-portal blocks that
 * *override* accents (`[data-portal="teacher"]` and friends), and a manifest
 * colour has no portal — an installed app is one icon and one splash screen for
 * whichever role signs in. Taking the `:root` value is therefore the correct
 * reading and not merely the convenient one.
 */
export function parseRootTokens(css: string): Map<string, [number, number, number]> {
  const start = css.indexOf(":root {")
  if (start === -1) {
    throw new Error("brandTokens: no `:root {` block in index.css — the token layer has moved.")
  }
  // Up to the first closing brace at column 0, which is how this file formats
  // the end of a top-level block. Matching braces properly would be better, but
  // `:root` here contains no nested blocks and a wrong answer throws below.
  const end = css.indexOf("\n}", start)
  const block = css.slice(start, end === -1 ? undefined : end)

  const tokens = new Map<string, [number, number, number]>()
  const pattern = /--([\w-]+):\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/g
  for (const match of block.matchAll(pattern)) {
    tokens.set(match[1], [Number(match[2]), Number(match[3]), Number(match[4])])
  }
  return tokens
}

/**
 * One token, as a hex string, read fresh off disk.
 *
 * Not cached. This runs a handful of times in a build, and a cache would mean a
 * dev server that keeps serving a stale colour after `index.css` is edited.
 */
export function tokenHex(name: string): string {
  const tokens = parseRootTokens(readFileSync(INDEX_CSS, "utf8"))
  const value = tokens.get(name)
  if (!value) {
    throw new Error(
      `brandTokens: \`--${name}\` is not declared as an oklch() value in :root of ` +
        `${INDEX_CSS}. The PWA manifest, the theme-color meta tag and the generated app ` +
        `icons all read it from there. If the token was renamed, update the callers; ` +
        `do not transcribe a hex, which is the drift this module exists to remove.`,
    )
  }
  return toHex(oklchToSrgb(...value))
}
