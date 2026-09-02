import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "./lib/queryClient"
import { AuthProvider } from "./lib/auth/AuthContext"
import { router } from "./App"
import { registerPushClientBridge } from "./lib/push/pushClientBridge"
import { reportClientError } from "./lib/clientErrors"
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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
