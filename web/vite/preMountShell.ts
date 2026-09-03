import type { Plugin } from "vite"
import { readFileSync } from "node:fs"
import { INDEX_CSS, tokenHex } from "./brandTokens.ts"

/*
 * Substitutes the pre-mount shell's colour and duration placeholders in
 * `index.html` (PR 2 part B).
 *
 * ── What the shell is, and why it cannot use CSS custom properties ─────────
 *
 * DESIGN.md §12's loading tiers apply in two places: inside the app
 * (`RouteFallback`, driven by `index.css`'s tokens and classes) and BEFORE the
 * app exists at all, as static markup inside `<div id="root">` that
 * `createRoot(...).render()` throws away the instant React's first commit
 * lands. That second copy paints before `index.css` has been requested, so it
 * cannot reach `var(--paper)` or `var(--loading-tier-slow)` — same shape of
 * problem `themeColor.ts` solves for `<meta name="theme-color">`, one more
 * consumer that is not the CSS cascade.
 *
 * So `index.html` carries seven colour placeholders (`%LEMELY_COLOR_PAPER%`
 * and six siblings) and two duration placeholders
 * (`%LEMELY_LOADING_TIER_SKELETON%` / `%LEMELY_LOADING_TIER_SLOW%`), and this
 * plugin is the one place that resolves all nine, at build time, from the same
 * two sources of truth everything else in this repo already answers to:
 * `tokenHex` (`brandTokens.ts`, the OKLCH → hex path `themeColor.ts` also
 * uses) for colour, and a direct read of `index.css`'s `--loading-tier-*`
 * declarations for duration. Duplicating `200ms` and `5000ms` as literals here
 * instead would be exactly the drift `brandTokens.ts`'s own header describes:
 * a transcription that is correct on the day it is written and silently wrong
 * the first time someone tunes a tier on the DESIGN.md/index.css side and
 * never thinks to grep index.html for a second copy.
 *
 * ── Why it throws on a missing placeholder ──────────────────────────────────
 *
 * Same reasoning as `themeColor.ts` and `fontPreload.ts`: a placeholder
 * removed by an unrelated edit (someone rewrites the shell markup, a merge
 * drops a line) would leave `%LEMELY_COLOR_PAPER%` or a raw `ms` value sitting
 * in the shipped HTML, or — worse, if the regex were looser — silently stop
 * substituting while the build still succeeds. The failure has to be loud at
 * build time, because nothing that renders this file (a browser painting
 * before any JS has run) is in a position to report it.
 *
 * `fillPreMountShell` also asserts, as its last step, that no
 * `%LEMELY_COLOR_..._%` or `%LEMELY_LOADING_TIER_..._%`-shaped placeholder
 * (this plugin's two families) survives the substitutions above — the
 * mirror-image failure to the one this section describes: a NEW placeholder
 * typed into index.html with no corresponding entry added to
 * `COLOR_PLACEHOLDERS`/`DURATION_PLACEHOLDERS` here would otherwise pass
 * every per-placeholder check (there is nothing to find it missing) and ship
 * as literal text in the page. Scoped to those two prefixes rather than every
 * `%LEMELY_..._%` in the document, so it does not misreport
 * `themeColor.ts`'s own `%LEMELY_THEME_COLOR%` (resolved by a separate
 * plugin) as this one's failure to resolve.
 */

const COLOR_PLACEHOLDERS: Readonly<Record<string, string>> = {
  "%LEMELY_COLOR_PAPER%": "paper",
  "%LEMELY_COLOR_PAPER_SUNK%": "paper-sunk",
  "%LEMELY_COLOR_PAPER_RAISED%": "paper-raised",
  "%LEMELY_COLOR_RULE%": "rule",
  "%LEMELY_COLOR_INK%": "ink",
  "%LEMELY_COLOR_INK_MUTED%": "ink-muted",
  "%LEMELY_COLOR_ACCENT%": "accent",
}

/** Placeholder -> the `--token-name` `index.css` declares it under. */
const DURATION_PLACEHOLDERS: Readonly<Record<string, string>> = {
  "%LEMELY_LOADING_TIER_SKELETON%": "loading-tier-skeleton",
  "%LEMELY_LOADING_TIER_SLOW%": "loading-tier-slow",
}

/**
 * Reads `--loading-tier-skeleton` and `--loading-tier-slow` off a copy of
 * `index.css`'s source text, so the pre-mount shell's two duration
 * placeholders resolve to whatever `index.css` actually declares rather than a
 * value re-typed here.
 *
 * A plain regex per token, not `parseRootTokens` from `brandTokens.ts`: that
 * parser is scoped to `oklch(...)` colour declarations specifically (see its
 * own doc comment), and these two tokens are plain `<time>` values.
 *
 * Exported so `tests/unit/preMountShell.test.ts` can exercise the parsing (and
 * the throw on a missing token) without going through a full plugin run.
 */
export function readLoadingTierDurations(css: string): Record<string, string> {
  const durations: Record<string, string> = {}
  for (const [placeholder, tokenName] of Object.entries(DURATION_PLACEHOLDERS)) {
    const pattern = new RegExp(`--${tokenName}:\\s*([\\d.]+m?s)\\s*;`)
    const match = css.match(pattern)
    if (!match) {
      throw new Error(
        `preMountShell: no \`--${tokenName}\` declaration found in ${INDEX_CSS}. The ` +
          "pre-mount shell reads its two tier durations from there so it cannot drift from " +
          "RouteFallback's; if the token was renamed, update DURATION_PLACEHOLDERS in " +
          "web/vite/preMountShell.ts to match.",
      )
    }
    durations[placeholder] = match[1]
  }
  return durations
}

/**
 * Replaces every colour and duration placeholder in the pre-mount shell's
 * markup. Exported separately from the plugin so the test suite can run it
 * over the real `index.html` source with no Vite build in the loop.
 */
export function fillPreMountShell(html: string): string {
  let out = html

  for (const [placeholder, tokenName] of Object.entries(COLOR_PLACEHOLDERS)) {
    if (!out.includes(placeholder)) {
      throw new Error(
        `preMountShell: index.html no longer contains ${placeholder}. The pre-mount shell's ` +
          "colours are injected from design tokens at build time, never written as literal " +
          "hex — a hardcoded value there would be unreachable by every gate in this repo, " +
          "the same failure themeColor.ts exists to prevent for the theme-color meta tag.",
      )
    }
    out = out.replaceAll(placeholder, tokenHex(tokenName))
  }

  const durations = readLoadingTierDurations(readFileSync(INDEX_CSS, "utf8"))
  for (const [placeholder, value] of Object.entries(durations)) {
    if (!out.includes(placeholder)) {
      throw new Error(
        `preMountShell: index.html no longer contains ${placeholder}. The pre-mount shell's ` +
          "tier durations are read from index.css at build time so they cannot drift from " +
          "RouteFallback's.",
      )
    }
    out = out.replaceAll(placeholder, value)
  }

  // Every KNOWN placeholder above is checked for presence before it is
  // replaced, which catches one gone missing. It does not catch the mirror
  // failure: a NEW `%LEMELY_COLOR_..._%` or `%LEMELY_LOADING_TIER_..._%`
  // placeholder added to index.html's markup with no matching entry in
  // COLOR_PLACEHOLDERS/DURATION_PLACEHOLDERS above, which would sail through
  // every check above untouched and ship as literal text in the rendered
  // page — a browser painting `%LEMELY_COLOR_FOO%` where a colour belongs, on
  // the one screen no test that renders the real app ever exercises. This is
  // the backstop: after every known substitution has run, nothing shaped
  // like one of THIS plugin's two placeholder families may remain.
  //
  // Scoped to those two prefixes, not every `%LEMELY_..._%` in the document:
  // `themeColor.ts` owns a third placeholder, `%LEMELY_THEME_COLOR%`, on the
  // same `<meta name="theme-color">` line, resolved by its own plugin in its
  // own build step — a bare `%LEMELY_[A-Z_]+%` sweep here would misreport
  // that one as this plugin's failure to resolve.
  const leftover = out.match(/%LEMELY_(?:COLOR|LOADING_TIER)_[A-Z_]+%/g)
  if (leftover) {
    throw new Error(
      `preMountShell: index.html still contains unresolved placeholder(s) after every known ` +
        `substitution ran: ${[...new Set(leftover)].join(", ")}. Add an entry to ` +
        "COLOR_PLACEHOLDERS or DURATION_PLACEHOLDERS in web/vite/preMountShell.ts, or remove " +
        "the placeholder from index.html if it is no longer needed.",
    )
  }

  return out
}

/** Build and dev alike: unlike `fontPreload` this needs no hashed asset name,
 * so the pre-mount shell renders correctly under `vite dev` too — useful,
 * since that is the fastest way to eyeball a tier while working on it. */
export function preMountShell(): Plugin {
  return {
    name: "lemely-pre-mount-shell",
    transformIndexHtml: {
      // `pre`, like `themeColor`: plain text substitution on the authored
      // HTML, with no interest in the bundle.
      order: "pre",
      handler(html) {
        return fillPreMountShell(html)
      },
    },
  }
}
