import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "./lib/queryClient"
import { AuthProvider } from "./lib/auth/AuthContext"
import { router } from "./App"
import { registerPushClientBridge } from "./lib/push/pushClientBridge"
import { currentBuildId, reportClientError } from "./lib/clientErrors"
import { installStaleChunkReload, StaleChunkGuard } from "./lib/staleChunk"
import { RecoveryEffects } from "./components/recovery-effects"
import { ToastProvider } from "./components/ui/toast"
import "./index.css"

// The page half of the push handshake (D5.15 §2). Registered once at startup,
// before the app renders: a push can arrive at any moment a tab is open, and a
// listener installed inside a screen would only answer while that screen
// happened to be mounted. Without this every push falls back to the generic
// notification even with the app open.
registerPushClientBridge()

/*
 * PR 1B (client error reporting): the two failure classes `ErrorBoundary`
 * cannot see. Same reasoning as `registerPushClientBridge` above — a listener
 * installed inside a screen only answers while that screen happens to be
 * mounted, and both of these can fire from code with no screen mounted at
 * all (a query's background refetch, a timer, a rejected promise nobody
 * awaited). Installed once, before the app renders, so nothing in the first
 * paint can throw ahead of these being armed.
 *
 * `event.error` is `null` for a small set of browsers/cases (notably a
 * cross-origin script error reported as "Script error." with no detail);
 * falling back to `event.message` keeps that case from reporting a message
 * of `"null"`. `event.message` can itself be `""` (an `ErrorEvent` fired by
 * hand with no message, say), so the final fallback is the literal
 * "Unknown error" rather than letting an empty string through —
 * `describeThrown` in `clientErrors.ts` does the same mapping for a caught
 * value with no message of its own, for the same reason: the backend's DTO
 * requires at least one character on `message`.
 */
window.addEventListener("error", (event) => {
  reportClientError({
    error: event.error ?? (event.message || "Unknown error"),
    kind: "unhandled",
  })
})
window.addEventListener("unhandledrejection", (event) => {
  reportClientError({ error: event.reason, kind: "rejection" })
})

/*
 * PR 2 part C (stale-chunk recovery): every portal screen is a lazy
 * `import()` (see the `P6.1b` notes in `portals/*\/index.tsx`), so a deploy
 * that lands while this tab still has the previous build open leaves this
 * tab's chunk URLs pointing at assets the CDN no longer serves. Installed
 * here, next to the error listeners above, for the same reason they are:
 * `vite:preloadError` can fire before any screen has mounted. See
 * `lib/staleChunk.ts` for the reload-at-most-once-per-build guard this
 * wires up, and `components/recovery-effects.tsx` for the "Updated to the
 * latest version" toast that announces a reload this guard caused.
 */
installStaleChunkReload({
  guard: new StaleChunkGuard(window.localStorage),
  buildId: currentBuildId(),
  reload: () => window.location.reload(),
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          {/* Mounted once, above the router, so both of its effects (the
              offline→online query refetch + "Reconnected" toast, and the
              post-reload "Updated" toast) run for the app's whole lifetime
              rather than only while some particular screen is mounted. */}
          <RecoveryEffects />
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
