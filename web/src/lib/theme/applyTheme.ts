import type { ResolvedTheme } from "./theme"

/**
 * The `theme-color` meta's `content` value for a resolved theme, read off
 * its own `data-theme-light`/`data-theme-dark` attributes — `vite/
 * themeColor.ts` writes both at build time, resolved from the light/dark
 * `--paper` tokens (see that file's header for why a `<meta>` needs a
 * pre-resolved hex rather than a `var()`, the same constraint `brandTokens.ts`
 * documents for every non-CSS consumer). A pure helper, exported separately
 * from `applyTheme` below so a test can exercise the lookup without a real
 * DOM mutation, and so `applyTheme` and `shell-init.js`'s own inline version
 * of this same lookup can be pinned against each other.
 */
export function themeColorFor(meta: HTMLMetaElement | null, theme: ResolvedTheme): string | undefined {
  if (!meta) return undefined
  return theme === "dark" ? meta.dataset.themeDark : meta.dataset.themeLight
}

/**
 * Applies a resolved theme to the document: sets the `data-theme` attribute
 * `index.css`'s dark ladder (Task 12) switches on, and swaps `<meta
 * name="theme-color">`'s content to match — a mobile browser's address bar
 * and an installed PWA's status bar both read that tag (pwa-expert).
 *
 * Takes `root`/`meta` as parameters rather than reaching for `document`
 * itself so `useTheme`'s layout effect can call it with the real document
 * while a test calls it with plain stand-in objects — and so this one
 * function is the single place both the toggle (via `useTheme`) and the
 * flash-free pre-mount path stay in agreement about what "apply a theme"
 * means, even though `shell-init.js` has to duplicate the logic rather than
 * import it (it runs before any bundle exists — see its own comment).
 */
export function applyTheme(root: HTMLElement, meta: HTMLMetaElement | null, theme: ResolvedTheme): void {
  root.dataset.theme = theme
  const color = themeColorFor(meta, theme)
  if (meta && color) {
    meta.content = color
  }
}
