import { useState } from "react"
import { WaitlistClientContext, WaitlistProvider } from "@/portals/marketing/waitlist/WaitlistDialog"
import type { WaitlistClient } from "@/portals/marketing/waitlist/WaitlistPanel"
import { ComingSoon, type Variant } from "./ComingSoon"

/** Fake network so the real waitlist dialog works without an API. */
const fakeClient: WaitlistClient = {
  join: async () => {
    await new Promise((r) => setTimeout(r, 600))
    return { status: "created", token: "preview-token" }
  },
  complete: async () => {
    await new Promise((r) => setTimeout(r, 600))
  },
  config: async () => ({ turnstileSiteKey: null, consentVersion: "2026-11-v1", consentText: "Applying opts you in to Lemely emails." }),
}

const VARIANTS: { id: Variant; label: string }[] = [
  { id: "a", label: "A · Say hi" },
  { id: "b", label: "B · Peek + say hi" },
  { id: "c", label: "C · Peek" },
]

export function Preview() {
  const qs = new URLSearchParams(location.search)
  const bare = qs.get("bare") === "1"
  const [v, setV] = useState<Variant>((qs.get("v") as Variant) || "a")
  const pick = (id: Variant) => {
    setV(id)
    qs.set("v", id)
    history.replaceState(null, "", `?${qs.toString()}`)
  }
  return (
    <WaitlistClientContext.Provider value={fakeClient}>
      <WaitlistProvider>
        {bare ? null : (
          <div className="cs-bar" role="toolbar" aria-label="Preview controls">
            <b>Coming soon preview</b>
            <span className="grp">
              {VARIANTS.map((x) => (
                <button key={x.id} type="button" aria-pressed={v === x.id} onClick={() => pick(x.id)}>
                  {x.label}
                </button>
              ))}
            </span>
          </div>
        )}
        <ComingSoon variant={v} />
      </WaitlistProvider>
    </WaitlistClientContext.Provider>
  )
}
