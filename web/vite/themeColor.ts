import type { Plugin } from "vite"
import { tokenHex } from "./brandTokens.ts"

/*
 * Substitutes `%LEMELY_THEME_COLOR%` in `index.html` with the real `--paper`
 * token (P6.5).
 *
 * `<meta name="theme-color">` is what a mobile browser paints its own chrome
 * with — the address bar on Android Chrome, the status bar area of an installed
 * PWA. It cannot hold a `var()`, because it is read before and outside the
 * cascade, so it is the third place in this build where a value has to be
 * resolved for a non-CSS consumer (see `brandTokens.ts` for the other two and
 * D5.1 for the general shape).
 *
 * It carried `#1e1310` — a near-black build-era brown — while every page in the
 * product is warm paper. So on a phone, the one device the brief says students
 * live on, the browser drew a dark bar directly above a light page, on all 48
 * routes, for the entire redesign. It is the same defect class as the icons:
 * rendered by the OS rather than by the app, and therefore invisible to every
 * gate here, none of which photograph browser chrome.
 *
 * **`--paper`, not `--ink`.** The value should continue the page rather than
 * frame it: the marketing header, all four portal shells and the auth frame are
 * `bg-paper`, so a paper-coloured browser bar makes the page appear to run to
 * the top of the screen. That is the whole point of the tag.
 *
 * A placeholder plus a hard failure, rather than editing whatever hex happens
 * to be in the file: an unmatched regex would leave the old colour in place and
 * succeed, which is precisely the silent-drift failure this pair of modules
 * exists to remove.
 *
 * ── Task 13 (C5b): a second, dark value ─────────────────────────────────────
 *
 * The meta tag itself still carries one `content`, resolved for whichever
 * theme is active — a `<meta>` cannot hold two values at once any more than
 * it can hold a `var()`. So it *also* carries both resolved colours as its
 * own `data-theme-light`/`data-theme-dark` attributes, which is what lets
 * `public/shell-init.js` (no bundle, no imports, runs before React exists)
 * and `applyTheme.ts` (the real app, after mount) swap `content` between them
 * with no second source of truth to keep in sync — they read this tag's own
 * attributes rather than re-deriving a hex themselves.
 */

const PLACEHOLDER = "%LEMELY_THEME_COLOR%"
const PLACEHOLDER_DARK = "%LEMELY_THEME_COLOR_DARK%"

/**
 * Replaces both theme-color placeholders in the real `<meta
 * name="theme-color">` tag. Exported separately from the plugin — the same
 * `fillPreMountShell`/`preMountShell` split `vite/preMountShell.ts` uses — so
 * the test suite can run it over the real `index.html` source with no Vite
 * build in the loop.
 */
export function fillThemeColor(html: string): string {
  if (!html.includes(PLACEHOLDER)) {
    throw new Error(
      `themeColor: index.html no longer contains ${PLACEHOLDER}. The theme-color meta ` +
        "tag is injected from the --paper token at build time; a hardcoded hex there " +
        "would drift silently, which is what P6.5 found it had already done.",
    )
  }
  if (!html.includes(PLACEHOLDER_DARK)) {
    throw new Error(
      `themeColor: index.html no longer contains ${PLACEHOLDER_DARK}. The dark ` +
        "theme-color value is injected from the dark --paper token (index.css's " +
        '`:root[data-theme="dark"]` block, Task 12) the same way the light one is, ' +
        "for shell-init.js and applyTheme.ts to swap the meta's content between at runtime.",
    )
  }
  return html
    .replaceAll(PLACEHOLDER_DARK, tokenHex("paper", "dark"))
    .replaceAll(PLACEHOLDER, tokenHex("paper"))
}

export function themeColor(): Plugin {
  return {
    name: "lemely-theme-color",
    transformIndexHtml: {
      // `pre`: this is a plain text substitution on the authored HTML and has
      // no interest in the bundle, unlike `fontPreload`, which must run `post`
      // to see hashed asset names.
      order: "pre",
      handler(html) {
        return fillThemeColor(html)
      },
    },
  }
}
