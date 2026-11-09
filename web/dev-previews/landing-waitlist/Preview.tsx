import { useEffect, useState } from "react"
import { RouterProvider, createMemoryRouter } from "react-router-dom"
import { MarketingLanding } from "@/portals/marketing"
import { WaitlistClientContext } from "@/portals/marketing/waitlist/WaitlistDialog"
import { WaitlistPanel, type WaitlistClient, type WaitlistSeed } from "@/portals/marketing/waitlist/WaitlistPanel"
import { platformAdminRoute } from "@/portals/admin"
import { WaitlistError } from "@/lib/waitlist-api"
import type { AdminMode } from "./fakeApi"

/** Fake network: emails containing dup / rate / offline trigger those states. */
const fakeClient: WaitlistClient = {
  join: async (input) => {
    await new Promise((r) => setTimeout(r, 700))
    if (/offline/i.test(input.email)) throw new WaitlistError(0)
    if (/rate/i.test(input.email)) throw new WaitlistError(429)
    if (/dup/i.test(input.email)) return { status: "already_listed" }
    return { status: "created", token: "preview-token" }
  },
  complete: async () => {
    await new Promise((r) => setTimeout(r, 700))
  },
  config: async () => ({ turnstileSiteKey: null, consentVersion: "2026-11-v1", consentText: "Applying opts you in to Lemely emails." }),
}

const router = createMemoryRouter([{ path: "*", element: <MarketingLanding /> }], { initialEntries: ["/landing"] })
const adminRouter = createMemoryRouter([platformAdminRoute], { initialEntries: ["/platform/waitlist"] })

const SCENES: { cap: string; seed: WaitlistSeed; mobile?: boolean }[] = [
  { cap: "Neutral (step 1, nothing entered)", seed: { step: 1 } },
  { cap: "Step 1, student picked, mobile sheet", seed: { step: 1, role: "student", email: "student01@example.com" }, mobile: true },
  { cap: "Step 1, validation errors", seed: { step: 1, email: "student01@school", errors: { email: "Enter an email like name@school.com.", role: "Pick the option that fits you." } } },
  { cap: "Step 1, submitting, mobile", seed: { step: 1, role: "teacher", email: "teacher02@example.com", status: "submitting" }, mobile: true },
  { cap: "Step 1, network error", seed: { step: 1, role: "parent", email: "parent03@example.com", status: "network" } },
  { cap: "Step 1, rate-limited, mobile", seed: { step: 1, role: "centre_admin", email: "centre04@example.com", status: "rate" }, mobile: true },
  { cap: "Already on the list (skips step 2)", seed: { step: 1, role: "student", email: "student01@example.com", duplicate: true } },
  { cap: "Step 2, student, top 8 subjects + Other", seed: { step: 2, role: "student", email: "student01@example.com", levels: ["o_level"], subjects: ["biology", "physics"], boards: ["caie"] } },
  { cap: "Step 2, student, mobile sheet", seed: { step: 2, role: "student", email: "student01@example.com", levels: ["o_level"], subjects: ["biology"] }, mobile: true },
  { cap: "Step 2, picker open, searching", seed: { step: 2, role: "student", email: "student01@example.com", subjects: ["biology", "french"], pickerOpen: true } },
  { cap: "Step 2, centre administrator (no session)", seed: { step: 2, role: "centre_admin", email: "centre04@example.com", levels: ["o_level", "a_level"], subjects: ["chemistry", "economics"], centre: "Example Learning Centre" } },
  { cap: "Step 2, parent, error, mobile", seed: { step: 2, role: "parent", email: "parent03@example.com", errors: { subjects: "Pick at least one subject." } }, mobile: true },
  { cap: "Step 2, teacher, a selected subject kept visible + phone error", seed: { step: 2, role: "teacher", email: "teacher02@example.com", levels: ["as_level", "a_level"], subjects: ["french"], otherSubjects: ["Robotics"], phone: "12", whatsapp: true, errors: { phone: "That number looks too short or too long." } } },
  { cap: "Step 2, submitting", seed: { step: 2, role: "student", email: "student01@example.com", subjects: ["biology"], status: "submitting" } },
  { cap: "Success, student (Binny), mobile", seed: { step: "done", role: "student", email: "student01@example.com" }, mobile: true },
  { cap: "Success, teacher", seed: { step: "done", role: "teacher", email: "teacher02@example.com" } },
  { cap: "Success, parent", seed: { step: "done", role: "parent", email: "parent03@example.com" } },
  { cap: "Success, centre administrator", seed: { step: "done", role: "centre_admin", email: "centre04@example.com" } },
]

function Gallery() {
  return (
    <div className="lw-light lw-gallery">
      {SCENES.map((s) => (
        <figure key={s.cap}>
          <figcaption>{s.cap}</figcaption>
          <div className={`lw-frame ${s.mobile ? "mobile" : ""} lw-light flex flex-col`} style={{ background: "var(--md-surface-container-lowest)", boxShadow: "var(--shadow-panel)", maxHeight: 780, maxWidth: s.mobile ? 390 : 560 }}>
            {s.mobile ? <div className="lw-grab" aria-hidden /> : null}
            <WaitlistPanel seed={s.seed} mobile={s.mobile} client={fakeClient} onClose={() => {}} />
          </div>
        </figure>
      ))}
    </div>
  )
}

export function Preview() {
  const qs = new URLSearchParams(location.search)
  const bare = qs.get("bare") === "1"
  const [view, setView] = useState<"landing" | "modal" | "admin">((qs.get("view") as never) || "landing")
  const [theme, setTheme] = useState<"light" | "dark">((qs.get("theme") as never) || "light")
  const admin = (qs.get("admin") as AdminMode) || "data"
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".lw-bar")
    const set = () => document.documentElement.style.setProperty("--lw-bar", `${bar?.offsetHeight ?? 0}px`)
    set(); addEventListener("resize", set); return () => removeEventListener("resize", set)
  }, [])
  useEffect(() => {
    if (qs.get("open") === "1" && view === "landing") setTimeout(() => document.querySelector<HTMLButtonElement>(".brand-hero .brand-actions button")?.click(), 400)
  }, [view]) // eslint-disable-line react-hooks/exhaustive-deps
  const P = (v: string, on: boolean, set: () => void) => <button key={v} type="button" aria-pressed={on} onClick={set}>{v}</button>
  return (
    <>
      {bare ? null : <div className="lw-bar" role="toolbar" aria-label="Preview controls">
        <b>Waitlist preview</b>
        <span className="grp">{P("Landing + live dialog", view === "landing", () => setView("landing"))}{P("All modal states", view === "modal", () => setView("modal"))}{P("Admin queue", view === "admin", () => setView("admin"))}</span>
        <span className="grp"><b>App theme</b>{P("Light", theme === "light", () => setTheme("light"))}{P("Dark", theme === "dark", () => setTheme("dark"))}</span>
        {view === "admin" ? <span className="grp"><b>State</b>{(["data", "loading", "empty", "error"] as const).map((s) => P(s, admin === s, () => { qs.set("admin", s); location.search = qs.toString() }))}</span> : null}
        {view === "landing" ? <span className="grp"><span>Try emails containing "dup", "rate" or "offline" in the live dialog.</span></span> : null}
      </div>}
      {!bare && theme === "dark" && view !== "admin" ? <div className="lw-theme-demo"><b>Proof of light-only.</b> This strip follows the app theme (dark now). The landing and dialog below keep the light roles.</div> : null}
      <WaitlistClientContext.Provider value={fakeClient}>
        {view === "landing" ? <RouterProvider router={router} /> : null}
      </WaitlistClientContext.Provider>
      {view === "modal" ? <Gallery /> : null}
      {view === "admin" ? <RouterProvider router={adminRouter} /> : null}
    </>
  )
}
