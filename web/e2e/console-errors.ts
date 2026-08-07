import type { Page } from "@playwright/test"

/**
 * Collects console `error` messages and uncaught page errors so a spec can
 * assert zero of them, per QUALITY-BAR.md's console-error gate. Excludes the
 * browser's own "Failed to load resource: ... 4xx/5xx" logging, which fires
 * for ANY non-2xx response — including ones a spec deliberately triggers to
 * exercise an error state (a 403/422/429, for example). That noise isn't a
 * signal of an app bug the way a React warning or an uncaught exception is.
 *
 * Extracted from screenshots.spec.ts (P2.5.5, the original single copy) so
 * P3.10's five new E2E specs (P3.10 chunk d) each assert this the same way
 * rather than re-copying the filter a fourth, fifth, sixth... time.
 *
 * A deliberately-provoked error response can still surface as a console
 * error from the app's OWN error logging/rendering, not just the browser's
 * resource-load noise the filter above already excludes (e.g. a React
 * error boundary, or a library that logs a caught error to `console.error`).
 * A spec that provokes one on purpose should clear the returned array
 * afterward (`errors.length = 0`) rather than weakening this filter to hide
 * it — P3.9 chunk d's lesson, carried forward.
 */
export function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on("console", (msg) => {
    if (msg.type() === "error" && !/^Failed to load resource:/.test(msg.text())) {
      errors.push(`[console] ${msg.text()}`)
    }
  })
  page.on("pageerror", (err) => {
    errors.push(`[pageerror] ${err.message}`)
  })
  return errors
}
