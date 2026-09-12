import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { VitePWA } from "vite-plugin-pwa"
// Explicit `.ts` extension: tsconfig.node.json resolves as `nodenext`, which
// requires one. `allowImportingTsExtensions` is already set there.
import { fontPreload } from "./vite/fontPreload.ts"
import { themeColor } from "./vite/themeColor.ts"
import { preMountShell } from "./vite/preMountShell.ts"
import { buildManifest } from "./vite/manifest.ts"

// https://vite.dev/config/
// Function form (packet A5 review fix), not a plain object: `mode` — plain
// `vite build` defaults to `"production"`; `.github/workflows/deploy.yml`'s
// staging job passes `--mode staging` — decides whether the manifest's
// `scope_extensions` is present at all. See `vite/manifest.ts`'s own
// docstring for why that one member must never ship in a production build.
export default defineConfig(({ mode }) => ({
  // PR 1B (client error reporting): stamps every build with a short id so a
  // `POST /api/client-errors` report can be traced back to the code that
  // produced it. `GITHUB_SHA` is set by every GitHub Actions run (`deploy.yml`
  // builds with `npm run build`); sliced to 12 chars, the same short-SHA length
  // `git rev-parse --short` and GitHub's own commit UI use. Locally, where no
  // CI env var exists, this is always `"dev"` — good enough to see in a report
  // that it came from a developer machine rather than a real deploy, and
  // exactly the fallback `src/lib/clientErrors.ts` also uses when the define
  // below hasn't run at all (vitest's separate config never sees it).
  define: {
    __LEMELY_BUILD_ID__: JSON.stringify((process.env.GITHUB_SHA ?? "dev").slice(0, 12)),
  },
  plugins: [
    react(),
    tailwindcss(),
    // P6.3: the only cause Lighthouse ever named for a layout shift in this
    // product is "Web font loaded". See web/vite/fontPreload.ts.
    fontPreload(),
    // P6.5: `<meta name="theme-color">` from the --paper token. See
    // web/vite/themeColor.ts.
    themeColor(),
    // PR 2 part B: the static pre-mount shell's colour/duration placeholders
    // in index.html, resolved from the same tokens RouteFallback uses. See
    // web/vite/preMountShell.ts.
    preMountShell(),
    VitePWA({
      // Packet A7 (`silent-update-swap`): "autoUpdate" is vite-plugin-pwa's
      // own registerSW.ts short-circuiting straight to a silent
      // `location.reload()` the moment a new worker activates — its
      // `onNeedRefresh` callback is never even called in that mode, so
      // `useServiceWorkerUpdate`'s `needRefresh` could never become true no
      // matter what the app built around it. "prompt" is what makes
      // vite-plugin-pwa call `onNeedRefresh` (and hold the new worker in
      // `waiting`) instead, which is the gate `<UpdateToast>` needs to exist
      // at all.
      registerType: "prompt",
      // Packet A7: was `"script-defer"` (P6.3, kept below). Now `false` —
      // `useServiceWorkerUpdate` registers via `virtual:pwa-register/react`'s
      // `useRegisterSW`, mounted in `main.tsx`; injecting a second,
      // independent registration script alongside it would double-register
      // the worker (two separate Workbox instances, each with its own
      // `updateServiceWorker`), and only the React-driven one is wired to
      // `needRefresh`/`<UpdateToast>`. The parser-blocking concern below is
      // moot with no injected script at all: registration now happens from
      // React, after hydration, the same general timing `script-defer` gave.
      //
      // P6.3, preserved for the history: the default (`injectRegister:
      // "auto"`) emits a bare `<script src="/registerSW.js">` as the last
      // thing in `<head>` — no `defer`, no `async`, not a module — so it is
      // parser-blocking, and the parser has not reached `<body>` yet when it
      // stops. Lighthouse measured it at **301ms of render blocking on every
      // one of the 41 audited routes**, for 403 bytes whose entire job is to
      // register a service worker that has nothing to do until after first
      // paint.
      injectRegister: false,
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
      //
      // Factored out to `web/vite/manifest.ts` (packet A5) so
      // `tests/unit/manifest.test.ts` can import and assert on the built
      // manifest directly, without pulling in this whole config file — see
      // that module's own docstring for the full member-by-member rationale.
      manifest: buildManifest(mode),
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
        //
        // `screenshots/**` and `widgets/**` (packet A5): the manifest
        // install-screenshot JPEGs and the widget Adaptive Card
        // JSON/data — both read only by an OS's own install/widget surface,
        // never by the running app, the same "not shell" reasoning as the
        // font subsets above. `store-icon-1024.png`: the 1024px store
        // listing icon, likewise never fetched by the app itself.
        globIgnores: [
          "**/*-{cyrillic,cyrillic-ext,greek,greek-ext,vietnamese}-*.woff2",
          "screenshots/**",
          "widgets/**",
          "store-icon-1024.png",
        ],
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
}))
