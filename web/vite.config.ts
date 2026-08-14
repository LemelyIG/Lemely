import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { VitePWA } from "vite-plugin-pwa"
// Explicit `.ts` extension: tsconfig.node.json resolves as `nodenext`, which
// requires one. `allowImportingTsExtensions` is already set there.
import { fontPreload } from "./vite/fontPreload.ts"

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // P6.3: the only cause Lighthouse ever named for a layout shift in this
    // product is "Web font loaded". See web/vite/fontPreload.ts.
    fontPreload(),
    VitePWA({
      registerType: "autoUpdate",
      // P6.3. The default (`injectRegister: "auto"`) emits a bare
      // `<script src="/registerSW.js">` as the last thing in `<head>` — no
      // `defer`, no `async`, not a module — so it is parser-blocking, and the
      // parser has not reached `<body>` yet when it stops. Lighthouse measured
      // it at **301ms of render blocking on every one of the 41 audited
      // routes**, for 403 bytes whose entire job is to register a service
      // worker that has nothing to do until after first paint. Deferring it
      // changes nothing about when the worker becomes useful and takes the
      // whole product off the second entry in its own render-blocking list
      // (the first is the stylesheet, which has to block).
      injectRegister: "script-defer",
      // `injectManifest`, not the default `generateSW` (D5.15 §1). A generated
      // worker has no `push` listener at all, so D5.10's payload-less push had
      // nowhere to land — the backend could send a notification and nothing on
      // the client would render it. The handler now lives in `src/sw.ts`, where
      // `tsc -b`, oxlint and vitest can all see it; a hand-written file under
      // `public/` (the `workbox.importScripts` alternative) would be copied
      // verbatim and checked by nothing.
      //
      // The `workbox` block below became `injectManifest` and the precache
      // wiring it used to generate is now written out by hand in `src/sw.ts`.
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      // App shell only: precache built JS/CSS/fonts/icons so the SPA loads
      // offline. Never cache /api/* — student/teacher marks, grades, and
      // review-queue data are live and must not be served stale, and the
      // SSE/POST endpoints under it aren't meaningfully cacheable anyway.
      manifest: {
        name: "Lemely",
        short_name: "Lemely",
        description:
          "Lemely marks a student's photographed or uploaded past-paper attempt against the official marking scheme with method-mark awareness, returning per-question marks, grade, and weakness topics.",
        start_url: "/",
        display: "standalone",
        // Computed from index.css's student/default theme tokens via a real
        // oklch->sRGB conversion (culori formatHex): --ink oklch(0.2 0.02 35)
        // -> #1e1310, --bg oklch(0.97 0.007 40) -> #faf4f2. Both are in the
        // sRGB gamut, so the conversion is exact (no clipping).
        theme_color: "#1e1310",
        background_color: "#faf4f2",
        icons: [
          {
            src: "pwa-192x192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "maskable-icon-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      // Only the manifest is configured here now. `navigateFallback` and its
      // `/^\/api/` denylist are no longer plugin options under injectManifest —
      // they are the `NavigationRoute` in `src/sw.ts`, and the denylist is
      // load-bearing for the same reason the comment above gives: /api/* is
      // live marks and grades and must never be served from a cache.
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2}"],
        // P6.3. Every `@font-face` @fontsource emits carries a `unicode-range`,
        // so a browser rendering English never requests the Cyrillic, Greek or
        // Vietnamese subsets at all — they cost nothing precisely because they
        // are never fetched. Precaching them by name defeats that: the service
        // worker asks for each one explicitly at install, and the glob above
        // was naming all nine. **187KB of glyphs no English page can display,
        // downloaded on every student's first visit**, most of them on a phone
        // on mobile data.
        //
        // The trade is stated rather than hidden: online, nothing changes —
        // the browser still fetches one of these on demand the moment a glyph
        // needs it, e.g. a student whose name is not in latin. Offline, such a
        // name renders in the fallback face. Precache is the app *shell*, and a
        // subset reachable only through particular user data is not shell.
        globIgnores: ["**/*-{cyrillic,cyrillic-ext,greek,greek-ext,vietnamese}-*.woff2"],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // FastAPI backend (see plan). Frontend-first this run: falls back to the
      // stubbed API layer in src/lib/api when the backend is not running.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    // Same backend proxy as `server`, above — `vite preview` reads its own
    // key rather than inheriting `server.proxy`. Needed so the Puppeteer
    // audit runner (P2.5.6) can exercise the real built app, including the
    // PWA service worker (only generated by `build`, not the dev server),
    // against the live backend.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
