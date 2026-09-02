/// <reference types="vite/client" />

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
