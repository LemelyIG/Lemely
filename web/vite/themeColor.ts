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
 */

const PLACEHOLDER = "%LEMELY_THEME_COLOR%"

export function themeColor(): Plugin {
  return {
    name: "lemely-theme-color",
    transformIndexHtml: {
      // `pre`: this is a plain text substitution on the authored HTML and has
      // no interest in the bundle, unlike `fontPreload`, which must run `post`
      // to see hashed asset names.
      order: "pre",
      handler(html) {
        if (!html.includes(PLACEHOLDER)) {
          throw new Error(
            `themeColor: index.html no longer contains ${PLACEHOLDER}. The theme-color meta ` +
              "tag is injected from the --paper token at build time; a hardcoded hex there " +
              "would drift silently, which is what P6.5 found it had already done.",
          )
        }
        return html.replaceAll(PLACEHOLDER, tokenHex("paper"))
      },
    },
  }
}
