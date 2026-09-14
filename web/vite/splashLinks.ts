import type { Plugin } from "vite"
import { splashLinkTags } from "./splashScreens.ts"

/*
 * Substitutes `%LEMELY_SPLASH_LINKS%` in `index.html` with the 32
 * `apple-touch-startup-image` links `splashScreens.ts`'s `SPLASHES` matrix
 * describes (packet B1, `no-ios-splash-screens`).
 *
 * Same placeholder-substitution shape as `themeColor.ts` and
 * `preMountShell.ts`, and the same reason for it: this is markup that has to
 * exist in the shipped `index.html` before any JS runs (iOS reads it at boot,
 * long before React or even the pre-mount shell's own logic is relevant), so
 * it cannot be injected by a React component the way an ordinary `<link>`
 * would be.
 *
 * A placeholder plus a hard failure, rather than silently leaving whatever
 * text happens to already be at that spot: an unmatched regex here would
 * ship `%LEMELY_SPLASH_LINKS%` as literal text in the page (harmless, but a
 * silent regression) or, if the placeholder were ever removed from
 * `index.html` by an unrelated edit, would leave the splash matrix
 * un-injected entirely — the exact "boot to a blank white rectangle" defect
 * this whole packet exists to fix, with a build that still succeeds and says
 * nothing.
 */

const PLACEHOLDER = "%LEMELY_SPLASH_LINKS%"

export function splashLinks(): Plugin {
  return {
    name: "lemely-splash-links",
    transformIndexHtml: {
      // `pre`, like `themeColor.ts`: plain text substitution on the authored
      // HTML, no interest in the built bundle.
      order: "pre",
      handler(html) {
        if (!html.includes(PLACEHOLDER)) {
          throw new Error(
            `splashLinks: index.html no longer contains ${PLACEHOLDER}. The iOS splash-screen ` +
              "links are injected from vite/splashScreens.ts's SPLASHES matrix at build time; " +
              "removing the placeholder would silently ship with no apple-touch-startup-image " +
              "links at all, and iOS would boot to a blank white rectangle again.",
          )
        }
        return html.replaceAll(PLACEHOLDER, splashLinkTags())
      },
    },
  }
}
