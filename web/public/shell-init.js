/*
 * A6/A7 review fix (CSP HIGH 1). External so CSP's `script-src 'self'` (no
 * `unsafe-inline`, no nonce, no hash) permits it without weakening the
 * policy — see `index.html`'s own comment for the full story. Runs as an
 * early, parser-blocking `<script src>` (no defer/async), the same
 * synchronous-at-this-point-in-the-parse timing the inline version it
 * replaces had, so `data-shell` is still set before the shell markup below
 * it paints.
 */
;(function () {
  // Theme preference (C5b). Resolves and paints the theme BEFORE the shell
  // markup below is parsed, so a cold load in dark mode never flashes light
  // first — the same "runs early, parser-blocking, no defer/async" timing
  // the `data-shell` setter below relies on. Wrapped in its own try/catch,
  // separate from the click-handler block below: `localStorage` throws in
  // some contexts (private browsing, storage disabled by policy), and a
  // theme-resolution failure here must never stop `data-shell` from being
  // set afterwards.
  try {
    var storedTheme = null
    try {
      storedTheme = localStorage.getItem("lemely.theme")
    } catch (storageError) {
      storedTheme = null
    }
    var prefersDark = false
    try {
      prefersDark = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
    } catch (mediaError) {
      prefersDark = false
    }
    // Same three-way table as `src/lib/theme/theme.ts`'s `resolveTheme` —
    // this file cannot import that module (it runs before any bundle
    // exists), so the table is duplicated here in plain ES5;
    // `tests/unit/themeInit.test.ts` pins the two against each other.
    var resolvedTheme
    if (storedTheme === "light") {
      resolvedTheme = "light"
    } else if (storedTheme === "dark") {
      resolvedTheme = "dark"
    } else {
      resolvedTheme = prefersDark ? "dark" : "light"
    }
    document.documentElement.dataset.theme = resolvedTheme
    var themeMeta = document.querySelector('meta[name="theme-color"]')
    if (themeMeta) {
      var resolvedColor =
        resolvedTheme === "dark"
          ? themeMeta.getAttribute("data-theme-dark")
          : themeMeta.getAttribute("data-theme-light")
      if (resolvedColor) {
        themeMeta.setAttribute("content", resolvedColor)
      }
    }
  } catch (themeError) {
    // Never let a theme-resolution failure block the data-shell setter
    // below — worst case the shell paints in the light ladder.
  }

  // Sets `data-shell="portal"` on `#root` before the shell markup is parsed,
  // so the browser never paints the portal chrome skeleton and then has to
  // hide it again for a non-portal path. Portal prefixes read off
  // `src/routes.tsx`: `studentRoute`/`teacherRoute`/`parentRoute` mount at
  // `/student`, `/teacher`, `/parent`; the two admin lanes
  // (`schoolAdminRoute`/`platformAdminRoute`) mount at `/school` and
  // `/platform` — there is no literal `/admin` route in this router.
  if (/^\/(student|teacher|parent|school|platform)(\/|$)/.test(location.pathname)) {
    document.getElementById("root").dataset.shell = "portal"
  }

  // The tier 3 "Still loading" reload button doesn't exist in the DOM yet at
  // this point — it's far below this script tag in source order — so a
  // direct `querySelector` here would find nothing. A delegated listener on
  // `document` (which always exists) works regardless of when the button is
  // actually inserted.
  document.addEventListener("click", function (event) {
    if (event.target.closest(".lm-shell-reload")) {
      location.reload()
    }
  })
})()
