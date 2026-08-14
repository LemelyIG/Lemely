import type { Plugin } from "vite"

/*
 * Build-time `<link rel="preload">` injection for the faces that render on
 * first paint.
 *
 * ── Why this exists (P6.3) ──────────────────────────────────────────────────
 *
 * REDESIGN-MISSION §5 Phase 6.3 asks for "skeletons reserve space (CLS < 0.1)"
 * and "a font-display strategy". Those turned out to be the same item: every
 * layout shift Lighthouse attributes in this product is caused by a *web font*
 * landing, and no skeleton is involved at all.
 *
 * **The numbers that first motivated this file were stale, and the record says
 * so rather than quietly keeping them.** A corpus at `reports/phase-6/` showed
 * `teacher-quiz-detail` at CLS 0.2427 and `teacher-schemes` at 0.1807, both
 * naming "Web font loaded" — and both citing
 * `instrument-serif-latin-400-normal-*.woff2`, a face Phase 2 replaced with
 * Newsreader. That font has not been in the bundle since, and the crisis was
 * three phases dead. Measured against HEAD: 41 routes, 0 over CLS 0.1, and
 * those two routes measure 0.0000.
 *
 * What survives the correction, and why this file still ships: the one
 * remaining shift is `student-overview` at 0.0982, the product's most-visited
 * screen, and its attributed cause is the same one — Newsreader, Caveat and
 * JetBrains Mono landing together on the Momentum panel. Build-era D6.9 warns
 * that this number is not reproducible ("a fast run hides the shifts
 * entirely"), so a single after-run cannot distinguish *fixed* from *fast*.
 * The honest defence of a preload is therefore not any after-number: it is
 * that a preload **removes the race rather than winning it** — the face is
 * discovered in the HTML instead of three steps into the CSS, so there is no
 * window in which the fallback is painted and then replaced. That argument
 * does not depend on which run you look at. See D6.4 §0.
 *
 * The mechanism is `font-display: swap`, which @fontsource sets on every face
 * and which is the right choice — `block` hides text and `optional` can drop
 * the brand faces entirely on a slow connection, which on a product whose one
 * protected quality is a *look* is worse than a reflow. `swap` is kept. What
 * was missing is that a font referenced only from a stylesheet is not
 * discovered until that stylesheet has downloaded AND parsed AND the first box
 * needing it has been laid out, so the fallback is always painted first and
 * every line of the page then re-flows when the real face lands.
 *
 * A preload moves the discovery to the HTML, so the face is in flight
 * alongside the CSS instead of after it.
 *
 * ── Why a plugin rather than a hand-written <link> in index.html ────────────
 *
 * Vite content-hashes the emitted woff2 filenames
 * (`geist-latin-wght-normal-BgDaEnEv.woff2`), so a hand-written href is correct
 * exactly until the next time a font package updates, and then it 404s while
 * still *looking* right in review. The bundle is the only honest source for
 * these names.
 *
 * ── Why it throws ──────────────────────────────────────────────────────────
 *
 * The failure mode this guards against is silent: if a face is renamed, or the
 * subset naming changes, or someone swaps the font package, the matcher stops
 * matching, no preload is emitted, the build still succeeds, the page still
 * renders, and the CLS quietly comes back. Nothing on screen says so. So a
 * missing critical face fails the build, in the same spirit as
 * `lib/nivoTheme.ts` refusing to draw a chart in the wrong colours rather than
 * drawing it (D5.1).
 */

/** A face that renders above the fold on essentially every route.
 *
 * `latin` only, and `normal` only. The `latin-ext` / `cyrillic` / `greek` /
 * `vietnamese` subsets each carry their own `unicode-range`, so a browser
 * rendering English never requests them and preloading one would be pure
 * waste; the italic files are likewise only fetched when italic text is
 * actually laid out.
 *
 * Caveat is deliberately absent. It is §4's marginalia face, it is the largest
 * latin subset in the product (~73KB against Geist's ~29KB), and it renders on
 * empty states and one landing-page sticker rather than on first paint. Its
 * `unicode-range`-gated download is already the lazy behaviour we want, and
 * preloading it would spend the most bandwidth on the least-seen face.
 */
interface CriticalFace {
  /** Matches the emitted asset filename, hash and all. */
  pattern: RegExp
  /** What breaks if it is missing — quoted back in the build error. */
  role: string
}

export const CRITICAL_FACES: readonly CriticalFace[] = [
  {
    pattern: /^geist-latin-wght-normal-[\w-]+\.woff2$/,
    role: "--font-sans, the UI and body face on every screen",
  },
  {
    pattern: /^newsreader-latin-wght-normal-[\w-]+\.woff2$/,
    role: "--font-display, every page title and section heading",
  },
  {
    pattern: /^jetbrains-mono-latin-wght-normal-[\w-]+\.woff2$/,
    role: "--font-mono, every mark, grade, XP figure and timer",
  },
]

/** Picks the preload set out of a built bundle's asset filenames.
 *
 * Exported separately from the plugin so `tests/unit/fontPreload.test.ts` can
 * exercise the matching and the throw without running a real Vite build.
 * Returns the names in `CRITICAL_FACES` order, which is also the order they
 * are wanted in: body text is the largest painted area, headings are the
 * largest single glyphs, data figures are the smallest.
 */
export function selectCriticalFontAssets(fileNames: readonly string[]): string[] {
  const selected: string[] = []
  const missing: string[] = []

  for (const face of CRITICAL_FACES) {
    const matches = fileNames.filter((name) => face.pattern.test(basename(name)))
    if (matches.length === 0) {
      missing.push(`${face.pattern.source} (${face.role})`)
      continue
    }
    // More than one match means the subset naming changed under us and the
    // pattern has stopped identifying a single face. Preloading both would
    // hide that, so it is reported the same way a miss is.
    if (matches.length > 1) {
      missing.push(
        `${face.pattern.source} matched ${matches.length} assets (${matches.join(", ")}) — expected exactly one`,
      )
      continue
    }
    selected.push(matches[0])
  }

  if (missing.length > 0) {
    throw new Error(
      "fontPreload: the build emitted no single asset for these critical faces, so the " +
        "preload that keeps CLS under 0.1 would have been silently dropped:\n  - " +
        missing.join("\n  - ") +
        "\nIf a font package was intentionally changed, update CRITICAL_FACES in " +
        "web/vite/fontPreload.ts to match the new filenames.",
    )
  }

  return selected
}

function basename(fileName: string): string {
  const slash = fileName.lastIndexOf("/")
  return slash === -1 ? fileName : fileName.slice(slash + 1)
}

/** Renders one preload tag.
 *
 * `crossorigin` is not optional and not cargo-cult, even though these fonts are
 * same-origin: CSS always fetches fonts in CORS mode, so a preload without it
 * is a *different* request in the browser's cache key. The face would be
 * downloaded twice and the preload would warn "preloaded but not used within a
 * few seconds" while fixing nothing.
 */
export function preloadTagFor(fileName: string, base: string): string {
  const href = `${base.replace(/\/$/, "")}/${fileName.replace(/^\//, "")}`
  return `<link rel="preload" as="font" type="font/woff2" href="${href}" crossorigin>`
}

/** Build-only. In dev the fonts are served unhashed straight out of
 * `node_modules` and there is no bundle to read names from; dev has no
 * first-paint budget worth defending either. */
export function fontPreload(): Plugin {
  // Read off the resolved config rather than `ctx.server`, which is undefined
  // during a build — the one mode this plugin runs in.
  let base = "/"
  return {
    name: "lemely-font-preload",
    apply: "build",
    configResolved(config) {
      base = config.base
    },
    transformIndexHtml: {
      // `post`, so the bundle exists and every asset has its final hashed name.
      order: "post",
      handler(html, ctx) {
        if (!ctx.bundle) return html
        const assets = selectCriticalFontAssets(Object.keys(ctx.bundle))
        const tags = assets.map((name) => preloadTagFor(name, base)).join("\n    ")
        return html.replace("</head>", `  ${tags}\n  </head>`)
      },
    },
  }
}
