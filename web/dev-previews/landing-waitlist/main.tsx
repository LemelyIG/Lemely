import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AuthProvider } from "@/lib/auth/AuthContext"
import "./preview.css"
import { blockApiFetch } from "../harness"
import { Preview } from "./Preview"
import { installFakeApi, type AdminMode } from "./fakeApi"

/* No API behind this page: any /api request hangs instead of failing. The waitlist client
   is replaced by a fake in Preview.tsx, so only unrelated hooks hit this. */
blockApiFetch()

const qs = new URLSearchParams(location.search)
if (qs.get("view") === "admin") {
  /* The real admin shell reads a session; this one is fake and only ever talks to fakeApi. */
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_")
  localStorage.setItem("lemely.session", JSON.stringify({ accessToken: `${b64({ alg: "none" })}.${b64({ exp: 4102444800 })}.x`, refreshToken: null, userId: "u1", role: "platform_admin" }))
  installFakeApi((qs.get("admin") as AdminMode) || "data")
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <Preview />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
