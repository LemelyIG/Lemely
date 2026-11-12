/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/react" />

/**
 * Short build/commit id, injected by `vite.config.ts`'s `define` block at
 * build time (a real SHA in CI, `"dev"` locally). `src/lib/clientErrors.ts`
 * reads it defensively — `typeof __LEMELY_BUILD_ID__ === "string"` — rather
 * than trusting this declaration alone, because `vitest.config.ts` is a
 * separate config that never runs the `define` substitution: a unit test
 * importing that module sees the bare, unreplaced identifier, which this
 * `declare const` makes legal to reference but does not make defined.
 */
declare const __LEMELY_BUILD_ID__: string

/**
 * The File Handling API (manifest's `file_handlers`, packet A6) — not yet in
 * TypeScript's own `lib.dom.d.ts`. `launchQueue` is optional on `Window`
 * because only a Chromium browser that launched this app via a registered
 * file handler ever sets it; every other browser leaves it `undefined`,
 * which is why `installFileHandlerBridge` (src/lib/sharedScan.ts) reads it
 * as `window.launchQueue?.`.
 *
 * A6 review fix (LOW): `files` is `FileSystemHandle[]` per the real spec,
 * not the narrower `FileSystemFileHandle[]` — `LaunchParams` is shared with
 * other launch shapes that can hand back a directory handle, so the base
 * type is what a consumer actually receives; narrowing to `FileSystemFileHandle`
 * (which alone has `.getFile()`) is the *consumer's* job, via `kind ===
 * "file"`, not this declaration's. `targetURL` was missing entirely.
 */
interface LaunchParams {
  readonly targetURL: string
  readonly files: readonly FileSystemHandle[]
}
interface LaunchQueue {
  setConsumer(consumer: (launchParams: LaunchParams) => void): void
}
interface Window {
  launchQueue?: LaunchQueue
}
