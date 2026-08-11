import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "./lib/queryClient"
import { AuthProvider } from "./lib/auth/AuthContext"
import { router } from "./App"
import { registerPushClientBridge } from "./lib/push/pushClientBridge"
import "./index.css"

// The page half of the push handshake (D5.15 §2). Registered once at startup,
// before the app renders: a push can arrive at any moment a tab is open, and a
// listener installed inside a screen would only answer while that screen
// happened to be mounted. Without this every push falls back to the generic
// notification even with the app open.
registerPushClientBridge()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
