/*
 * PR 2 part C · stale-chunk recovery.
 *
 * Every screen below a portal layout is `React.lazy` (see the `P6.1b` notes
 * in `portals/*\/index.tsx`), so navigating into one a session hasn't visited
 * yet fires a dynamic `import()` against a chunk URL baked into the currently
 * running bundle. When a deploy lands between that bundle being served and
 * that `import()` running, the old chunk URL is gone from the CDN — every
 * further lazy navigation in that tab throws instead of rendering, and stays
 * broken until the tab reloads. This is not a bug in the screen; it is a stale
 * *tab*.
 *
 * `isChunkLoadError` below is the classifier: does a thrown value look like
 * exactly that failure, as opposed to a real bug in the chunk's own code?
 * `StaleChunkGuard` is the loop guard: a reload fixes a genuinely stale tab,
 * but a tab reloaded onto a build that is *still* broken (a real error in the
 * new chunk, not a stale one) must not reload forever — so a reload is
 * attempted at most once per build id, tracked in storage so it survives the
 * reload itself. `installStaleChunkReload` wires both to the real browser:
 * Vite's own preload-failure event for a failed *module preload*, plus
 * `handleChunkError` as the same decision exposed for a route error screen to
 * call directly on a caught `import()` rejection (React Router surfaces a
 * failed lazy import as a thrown error on the route — it never goes through
 * Vite's `vite:preloadError` event at all, which only fires from Vite's own
 * generated `__vitePreload` wrapper).
 */

/**
 * Does `error` look like a browser's dynamic-`import()`-failed-to-load
 * error, as opposed to a real exception the imported module's own code
 * threw?
 *
 * The four literal phrases are the messages Chromium, Firefox and Safari are
 * each observed to produce for a failed module fetch and for Vite's own
 * `Unable to preload CSS for ...` (the `?.css` side of a chunk, thrown by the
 * `handlePreloadError` path `vite:preloadError`'s payload comes from — see
 * the module doc above). The `TypeError` check is a second, broader net for
 * a browser phrasing not on that list: every browser observed reports a
 * failed module fetch as a `TypeError` whose message mentions "dynamically
 * imported module", so a `TypeError` matching that phrase is treated as a
 * chunk-load failure even when its exact wording differs from the four
 * pinned strings.
 *
 * Matched case-insensitively and by substring, not exact equality: browsers
 * append the failing URL to the message, so an exact match would only ever
 * be right for the one URL a test happened to pick.
 */
export function isChunkLoadError(error: unknown): boolean {
  const message = extractMessage(error)
  if (message === null) return false
  const lower = message.toLowerCase()

  const matchesKnownPhrase = CHUNK_ERROR_PHRASES.some((phrase) => lower.includes(phrase))
  if (matchesKnownPhrase) return true

  return error instanceof TypeError && lower.includes("dynamically imported module")
}

const CHUNK_ERROR_PHRASES = [
  "failed to fetch dynamically imported module",
  "importing a module script failed",
  "error loading dynamically imported module",
  "unable to preload css",
] as const

/** `error`'s message, or `null` when `error` carries none (not an `Error`,
 * not a plain string). Mirrors `describeThrown` in `clientErrors.ts` in
 * spirit but stays narrower on purpose: this module only needs to read a
 * message to classify it, never to report it, so there is no stack, no
 * `String()` fallback for an arbitrary thrown object, and nothing here needs
 * `clientErrors.ts`'s defensive `safeRead` — a getter that throws on `.message`
 * is not a shape any real chunk-load failure takes. */
function extractMessage(error: unknown): string | null {
  if (error instanceof Error) return error.message
  if (typeof error === "string") return error
  return null
}

/** The subset of the `Storage` interface `StaleChunkGuard` needs — narrowed
 * from the full `Storage` (which also has `length`, `key`, and index access)
 * so a test can inject a minimal fake without implementing methods this
 * class never calls. */
export type ChunkGuardStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">

const RELOAD_KEY = "lemely:stale-chunk-reload"
const NOTICE_KEY = "lemely:stale-chunk-notice"

/**
 * `currentBuildId()` (`clientErrors.ts`) falls back to this literal outside
 * a real deploy (`vite dev`, and any other environment `__LEMELY_BUILD_ID__`
 * never gets defined in). Every such session shares the same "build id"
 * forever, so persisting it under `RELOAD_KEY` the way a real build id is
 * persisted would poison the guard for the rest of that browser profile's
 * life on that origin after the first reload — see `tryReload`/`canReload`
 * below for the fix.
 */
const DEV_BUILD_ID = "dev"

/**
 * The reload-at-most-once-per-build guard, backed by injected storage so it
 * is testable under vitest's node environment with no real
 * `localStorage` (see `vitest.config.ts`, D3.20).
 *
 * Two keys, both under the injected storage:
 *  - `RELOAD_KEY` holds the build id a reload has already been attempted
 *    for. `tryReload` refuses a second attempt for the same id — that is
 *    the entire loop guard: a build that is still broken after reloading
 *    (a real bug, not a stale deploy) must fail through to the "new
 *    version" screen instead of reloading forever. Never written for
 *    `DEV_BUILD_ID` — see `reloadedThisLoad` below.
 *  - `NOTICE_KEY` holds the *stale* build id `tryReload` reloaded away
 *    from, so `consumeReloadNotice` can tell a genuine recovery (the app
 *    is now running a different build than the one that failed) apart from
 *    a reload that landed back on the same build with nothing actually
 *    fixed — see `consumeReloadNotice` below for why that distinction
 *    matters to the toast it gates.
 *
 * Every storage access is wrapped in `try`/`catch`: Safari private
 * browsing and a full storage quota both make `localStorage` throw on
 * `setItem` (and, in some private-mode configurations, on `getItem` too),
 * and a throw here must never be the reason a stale-chunk reload fails to
 * happen — the guard degrading to "no guard" (every `tryReload` call
 * succeeds) is a strictly better failure mode than the reload never firing
 * at all.
 */
export class StaleChunkGuard {
  private readonly storage: ChunkGuardStorage

  /**
   * The in-memory half of the `DEV_BUILD_ID` special case: `vite dev` never
   * changes build ids across a reload, so persisted storage can never tell
   * "already reloaded once this load" apart from "already reloaded once,
   * ever, on this origin" for that id. Scoped to this instance (which lives
   * exactly as long as one real page load — a reload creates a fresh JS
   * context and a fresh `StaleChunkGuard`), so it resets exactly when a
   * genuine new load should get a fresh chance, and never survives a reload
   * to block the next one the way a persisted key would.
   */
  private reloadedThisLoad = false

  constructor(storage: ChunkGuardStorage) {
    this.storage = storage
  }

  private read(key: string): string | null {
    try {
      return this.storage.getItem(key)
    } catch {
      return null
    }
  }

  private write(key: string, value: string): void {
    try {
      this.storage.setItem(key, value)
    } catch {
      // Swallowed — see the class doc above.
    }
  }

  private clear(key: string): void {
    try {
      this.storage.removeItem(key)
    } catch {
      // Swallowed — see the class doc above.
    }
  }

  /**
   * Would `tryReload(buildId)` reload right now? A pure read with no side
   * effect — safe to call from a render body (`classifyRouteError`,
   * `lib/routeError.ts`, injects this as `canReload`) where `tryReload`
   * itself, which writes storage and is meant to be followed by an actual
   * `location.reload()`, is not.
   *
   * `DEV_BUILD_ID` is always eligible by persisted-storage standards (see
   * the class doc above for why persisting it at all would be a one-way
   * trip) — bounded instead by `reloadedThisLoad`, so a dev session still
   * cannot reload more than once per real page load.
   */
  canReload(buildId: string): boolean {
    if (buildId === DEV_BUILD_ID) return !this.reloadedThisLoad
    return this.read(RELOAD_KEY) !== buildId
  }

  /**
   * Should a chunk-load failure on `buildId` trigger a reload right now?
   * `true` at most once per distinct `buildId` — a second call with the
   * same id (this build is still broken after the one reload it already
   * got) returns `false`, so the caller can fall through to a "new
   * version" screen instead of looping. Delegates the decision to
   * `canReload`; the two must never disagree, since a caller checks one
   * (in render) and calls the other (in an effect) for the same outcome.
   */
  tryReload(buildId: string): boolean {
    if (!this.canReload(buildId)) return false
    if (buildId === DEV_BUILD_ID) {
      this.reloadedThisLoad = true
    } else {
      this.write(RELOAD_KEY, buildId)
    }
    this.write(NOTICE_KEY, buildId)
    return true
  }

  /**
   * Has a reload this guard caused just landed — and should the "Updated to
   * the latest version" toast fire because of it?
   *
   * `true` at most once per guard-caused reload: the first call after
   * `tryReload` set `NOTICE_KEY` consumes it (clears the key) and every
   * later call sees nothing pending and returns `false`, which is what
   * keeps the toast from reappearing on a later remount of
   * `RecoveryEffects` in the same session.
   *
   * Also gated on `buildId` actually having changed: `NOTICE_KEY` holds the
   * *stale* id the reload was attempted for, and if the app handed this
   * function that exact same id back, the reload did not actually reach a
   * new build (a CDN or browser cache still serving the old one, most
   * likely) — announcing "Lemely reloaded to pick up a new release" would
   * be false in that case, so this returns `false` instead, while still
   * consuming the pending notice so it cannot fire late once a real new
   * build does eventually load.
   *
   * A confirmed recovery (the changed-id case) also clears `RELOAD_KEY`:
   * the build that failed is gone for good now that a newer one has
   * loaded, so there is nothing left for that key to guard against, and
   * leaving it set would only ever cost a future, unrelated chunk failure
   * that happens to reuse the same id (unlikely, but free to rule out).
   */
  consumeReloadNotice(buildId: string): boolean {
    const pendingFor = this.read(NOTICE_KEY)
    if (pendingFor === null) return false
    this.clear(NOTICE_KEY)
    const recovered = pendingFor !== buildId
    if (recovered) this.clear(RELOAD_KEY)
    return recovered
  }
}

/**
 * The wiring for `handleChunkError` below — set once by
 * `installStaleChunkReload`, read by every call to `handleChunkError`
 * regardless of which caller (the `vite:preloadError` listener this
 * function installs, or a route error screen calling `handleChunkError`
 * directly) triggered it. Module state rather than a value threaded through
 * every call site: `handleChunkError` needs to be a plain, directly
 * importable function (see the module doc above — a route error screen
 * imports `isChunkLoadError` and `handleChunkError` as siblings), and
 * `main.tsx` is the one place that knows the real `guard`/`buildId`/
 * `reload` to wire it with.
 */
let installed: { guard: StaleChunkGuard; buildId: string; reload: () => void } | null = null

/**
 * Wire the stale-chunk guard to the real browser. Call once, before the app
 * renders (`main.tsx`, next to the PR 1B error listeners) — `vite:preloadError`
 * can fire before any screen has mounted, the same reasoning that puts those
 * listeners there.
 *
 * `event.preventDefault()` on the `vite:preloadError` handler stops Vite's
 * own fallback: unprevented, `handlePreloadError` (see the module doc above)
 * re-throws the original error past this listener, which would otherwise
 * turn every stale-chunk failure this guard successfully handles into an
 * uncaught error `main.tsx`'s own `window.addEventListener("error", ...)`
 * would then report as a crash — for a failure this function is about to fix
 * with a reload.
 */
export function installStaleChunkReload(opts: {
  guard: StaleChunkGuard
  buildId: string
  reload: () => void
}): void {
  installed = opts

  window.addEventListener("vite:preloadError", (event) => {
    event.preventDefault()
    handleChunkError((event as Event & { payload?: unknown }).payload)
  })
}

/**
 * The decision itself, callable from anywhere a chunk-load failure was
 * caught: the listener `installStaleChunkReload` installs above, or a route
 * `errorElement`/`ErrorBoundary` that caught a rejected dynamic `import()`
 * directly. Returns whether a reload was actually triggered, so a caller
 * (the route error screen this PR does not own) can fall through to its own
 * "new version" UI when it was not — either because `error` doesn't look
 * like a chunk-load failure at all, or because the guard already spent its
 * one reload on this build.
 *
 * `installed === null` (this ran before `installStaleChunkReload`, or in an
 * environment that never called it — a unit test importing this module
 * directly) is treated as "nothing to do" rather than thrown: this function
 * has no safe way to reload without the real `reload` callback, and a
 * classifier returning `false` is the correct answer to "was a reload
 * triggered" when none was.
 *
 * This function writes storage and calls `installed.reload()` — a real
 * side effect. `route-error.tsx` calls it from a `useEffect`, never from a
 * render body; `canReloadChunkError` below is the render-safe counterpart
 * that answers the same question without doing either.
 */
export function handleChunkError(error: unknown): boolean {
  if (!isChunkLoadError(error)) return false
  if (installed === null) return false
  if (!installed.guard.tryReload(installed.buildId)) return false
  installed.reload()
  return true
}

/**
 * Would `handleChunkError(error)` trigger a reload right now? Same question,
 * asked without writing storage or reloading anything — a pure predicate a
 * render body can call safely, unlike `handleChunkError` itself (see its own
 * doc above). `route-error.tsx` injects this as `classifyRouteError`'s
 * `canReload` so classification stays pure: calling it twice with the same
 * `error` is guaranteed to answer the same way, which `handleChunkError`
 * cannot promise (its second call for the same build always answers `false`,
 * having already spent the guard's one reload on the first).
 */
export function canReloadChunkError(error: unknown): boolean {
  if (!isChunkLoadError(error)) return false
  if (installed === null) return false
  return installed.guard.canReload(installed.buildId)
}
