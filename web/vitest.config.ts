import path from "node:path"
import { defineConfig } from "vitest/config"

/*
 * Unit-test runner for `web/` (P3.10 chunk e3, D3.20).
 *
 * Deliberately NOT an extension of `vite.config.ts`: that config loads the
 * React, Tailwind and PWA plugins, none of which a Node-environment unit test
 * needs, and the PWA plugin in particular writes a service worker as a side
 * effect of being configured. A separate file keeps the test run free of the
 * build pipeline.
 *
 * `environment: "node"` is a decision, not a default. There is no jsdom and no
 * @testing-library here: component behaviour is covered by the Playwright E2E
 * suite against the real browser and the real backend, and a second,
 * lower-fidelity component-rendering stack would duplicate that coverage while
 * being able to disagree with it. What this runner is for is the pure logic and
 * the repo invariants that no browser test can see — see D3.20.
 */
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  test: {
    environment: "node",
    include: ["tests/unit/**/*.test.ts"],
    // `e2e/` holds Playwright specs, which define their own `test`/`expect`
    // and hang if vitest picks them up.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
})
