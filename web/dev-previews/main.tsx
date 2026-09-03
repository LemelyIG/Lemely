import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AuthProvider } from "@/lib/auth/AuthContext"
import "./preview.css"
import { App } from "./App"

const root = document.getElementById("root")
if (!root) throw new Error("preview root element is missing")

/*
 * `MemoryRouter`, added in P3.2 when the kit gained its first components that
 * render a `<Link>` (Breadcrumbs, GettingStarted). Memory rather than browser
 * history on purpose: the preview's links point at real product routes that do
 * not exist in this entry, so a browser router would let a click navigate the
 * preview to a blank page. In memory the click is a no-op that still exercises
 * the component's real markup, which is what the page is here to show.
 */
/*
 * `AuthProvider` (and the `QueryClientProvider` its mutations need), added in
 * PR 2 part D when the kit gained the full-page states and the loading tiers:
 * `FullPageStateBody` resolves its "home" action through `useAuth()`, which
 * throws outside a provider, so without these the whole page failed to mount
 * and every cell above the crash was blank. The real provider rather than a
 * stub: with no stored session it resolves to "Go to sign in", which is the
 * honest state for a preview that has no signed-in reader. Nothing here
 * fires a request; the client exists only so `useMutation` has somewhere to
 * register.
 */
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
