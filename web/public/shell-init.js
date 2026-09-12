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
