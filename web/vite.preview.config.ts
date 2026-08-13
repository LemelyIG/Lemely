import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath, URL } from "node:url"

/**
 * Separate Vite entry for the component-kit preview page.
 *
 * REDESIGN-MISSION §5 Phase 2.6 requires an 8-state preview page for the
 * component kit. It gets its own config, root, and build output rather than
 * living as a route in the app, for two reasons:
 *
 * 1. **The product must never ship it.** A preview route inside `src/` is one
 *    forgotten guard away from being reachable in production, and it would drag
 *    every component in the kit into the main bundle whether a screen uses it
 *    or not.
 * 2. **It must not become a de-facto route.** Once a preview is addressable in
 *    the app, screens start linking to it and it stops being a preview.
 *
 * Run with `npm run preview:kit`. The `@` alias mirrors the app config so the
 * preview imports components by exactly the same specifier a real screen does,
 * which is what makes the preview trustworthy.
 */
export default defineConfig({
  root: fileURLToPath(new URL("./dev-previews", import.meta.url)),
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { port: 5199 },
  build: {
    outDir: fileURLToPath(new URL("./dist-previews", import.meta.url)),
    emptyOutDir: true,
  },
})
