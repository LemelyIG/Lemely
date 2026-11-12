import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider, createBrowserRouter } from "react-router-dom"
import "./preview.css"
import "../../src/portals/marketing/marketing.css"
import "../../src/portals/marketing/brand-tokens.css"
import "../../src/portals/marketing/brand.css"
import { WaitlistClientContext, WaitlistProvider } from "@/portals/marketing/waitlist/WaitlistDialog"
import type { WaitlistClient } from "@/portals/marketing/waitlist/WaitlistPanel"
import { ConfirmEmail } from "@/portals/marketing/waitlist/ConfirmEmail"

/*
 * The real /waitlist/confirm page with a mocked API, never shipped.
 *   ?state=loading|confirmed|already|invalid|expired|rate|network   (default confirmed)
 *   ?theme=light|dark   light = signed-out visitor, dark = signed-in user on the dark theme
 *   ?bare=1             hides the preview toolbar
 * Retrying a rate-limit or network failure succeeds, so the retry path is visible too.
 */
const STATES = ["loading", "confirmed", "already", "invalid", "expired", "rate", "network"] as const
type PreviewState = (typeof STATES)[number]

const qs = new URLSearchParams(location.search)
const state: PreviewState = (STATES as readonly string[]).includes(qs.get("state") ?? "")
  ? (qs.get("state") as PreviewState)
  : "confirmed"
const theme = qs.get("theme") === "dark" ? "dark" : "light"
const bare = qs.get("bare") === "1"
document.documentElement.dataset.theme = theme

// The page strips its own `?token=` from the address bar; keep ours so a reload stays on this state.
const realReplace = history.replaceState.bind(history)
history.replaceState = (data, unused, url) => {
  if (typeof url === "string" && !url.includes("?")) return
  realReplace(data, unused, url)
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
let calls = 0
const realFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url
  if (!new URL(url, location.href).pathname.startsWith("/api/waitlist/confirm")) return realFetch(input, init)
  calls += 1
  await new Promise((r) => setTimeout(r, 500))
  if (state === "loading") return new Promise<Response>(() => {})
  if (state === "confirmed") return json(200, { status: "confirmed" })
  if (state === "already") return json(200, { status: "already_confirmed" })
  if (state === "invalid") return json(400, { detail: { code: "invalid_token" } })
  if (state === "expired") return json(400, { detail: { code: "expired_token" } })
  if (calls > 1) return json(200, { status: "confirmed" })
  if (state === "rate") return json(429, { detail: "rate_limited" })
  throw new TypeError("Failed to fetch")
}

const client: WaitlistClient = {
  join: async () => ({ status: "created", token: "preview-token" }),
  complete: async () => {},
  config: async () => ({ turnstileSiteKey: null, consentVersion: "2026-11-v1", consentText: "Applying opts you in to Lemely emails." }),
}

// The page reads its token from the address bar on mount.
if (!qs.get("token")) {
  qs.set("token", "preview-token")
  realReplace(null, "", `?${qs.toString()}`)
}

function link(next: Record<string, string>) {
  const q = new URLSearchParams(location.search)
  q.delete("token")
  for (const [k, v] of Object.entries(next)) q.set(k, v)
  return `?${q.toString()}`
}

function Page() {
  return (
    <WaitlistClientContext.Provider value={client}>
        <WaitlistProvider>
          {bare ? null : (
            <nav className="pv-bar" aria-label="Preview controls">
              <b>Confirm page preview</b>
              <span className="grp">
                {STATES.map((s) => (
                  <a key={s} href={link({ state: s })} aria-current={s === state}>{s}</a>
                ))}
              </span>
              <span className="grp">
                {["light", "dark"].map((t) => (
                  <a key={t} href={link({ theme: t })} aria-current={t === theme}>
                    {t === "dark" ? "signed-in dark" : "signed-out light"}
                  </a>
                ))}
              </span>
            </nav>
          )}
          <div className="marketing-brand">
            <ConfirmEmail />
          </div>
        </WaitlistProvider>
      </WaitlistClientContext.Provider>
  )
}

const router = createBrowserRouter([{ path: "*", element: <Page /> }])

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
