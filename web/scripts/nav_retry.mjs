/*
 * Shared navigation-retry helper (packet A8, `emp-env-navigation-flakiness`).
 *
 * `audit.mjs` already had one narrow retry — `gotoReady`'s single re-goto on
 * a detached-frame error, specific to a real Puppeteer/vite-plugin-pwa
 * interaction (see that function's own comment for the full story). This
 * generalises the same idea to any transient navigation failure (a dropped
 * connection, a `vite preview` server that hasn't finished starting, a
 * Lighthouse pass that occasionally times out under CI's load) rather than
 * one specific error message, and gives `runLighthouseAudit`'s own
 * navigation (`lighthouse(url, ...)` drives its own internal `page.goto`,
 * so there is no `page.goto` call site to wrap there) the same resilience
 * through the shared `withRetry` primitive.
 */

/**
 * Retries `fn()` up to `attempts` times, logging each failure, and rethrows
 * the last error if every attempt fails. No backoff: every failure mode
 * this wraps (a detached frame, a server not quite up yet, a flaky
 * Lighthouse pass) resolves or doesn't within a handful of immediate
 * retries — adding a delay would only slow down the far more common case
 * where the first retry already succeeds.
 */
export async function withRetry(fn, { attempts = 3, label = "operation" } = {}) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn()
    } catch (err) {
      lastError = err
      const message = String(err?.message ?? err)
      console.warn(`  !! ${label} failed (attempt ${attempt}/${attempts}): ${message}`)
    }
  }
  throw lastError
}

/** `page.goto(url, options)`, retried up to `attempts` times on any failure
 * (navigation timeout, a `vite preview` server still coming up, a detached
 * frame). */
export async function gotoWithRetry(page, url, options = {}, attempts = 3) {
  return withRetry(() => page.goto(url, options), { attempts, label: `goto ${url}` })
}
