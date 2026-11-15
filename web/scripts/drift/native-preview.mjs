/*
 * The design A preview's native phone frame (student-home-a.html with
 * ?platform=ios|android&page=root|detail), as committed at 4447a571.
 * Selectors are read off the committed markup; update them here, nowhere else.
 * State hooks the scenes may wait on: `.as-bar.is-collapsed` (root, scrolled past
 * the large title), `.as-bar.is-raised` (bar surface shown), and
 * `.sh-root[data-sheet="medium|large|fit"]` (a phone sheet is open).
 * `settings` and `avatar` are visible on the root page only (the detail bar keeps back, title and bell).
 * No `platform` param means `other` (design A's own phone frame, no data-platform).
 */
export const NATIVE_PREVIEW = {
  root: ".sh-root",
  bar: ".as-bar",
  largeTitle: ".as-lt",
  inlineTitle: ".as-title",
  back: ".as-back",
  bell: ".as-pop-bell > summary",
  settings: '[data-a-open="as-settings"]',
  avatar: ".as-pop-me > summary",
  sheet: ".as-pop[open] > .as-pop-panel, .as-modal[open]",
  tabbar: ".a-bottombar",
  /* Pull-to-refresh indicators (root page only): the wrapper, the iOS 8-spoke
     activity indicator and the Android M3 disc. The content rests at
     --native-ptr-hold-ios (56px) or --native-ptr-hold-android (64px) while refreshing. */
  ptr: ".as-ptr",
  ptrIos: ".as-ptr-ios",
  ptrMd: ".as-ptr-md",
}

/** `width: "desktop"` on purpose: at a 390px viewport the shell container is
 * 390px, so the phone frame applies; `width=mobile` would add the preview
 * toolbar above the frame and into the capture. */
export function previewNativeQuery({ state, theme, platform, page }) {
  return new URLSearchParams({ state, theme, motion: "reduce", width: "desktop", platform, page })
}
