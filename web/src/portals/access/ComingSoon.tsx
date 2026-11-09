/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { Binny, type BinnyMood } from "@/portals/marketing/Binny"
import { WaitlistProvider, useWaitlist } from "@/portals/marketing/waitlist/WaitlistDialog"
import "@/portals/marketing/brand-tokens.css"
import "./coming-soon.css"

import { TEAM_SIGN_IN_PATH, TEAM_SIGN_UP_PATH } from "./team"

const PEEK_CYCLE: BinnyMood[] = ["open", "happy", "wink", "thinking"]

/** Pupils follow the pointer. Off under `prefers-reduced-motion`. */
function useTrack(ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    const el = ref.current
    if (!el) return
    const on = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      const dx = (e.clientX - (r.left + r.width / 2)) / Math.max(r.width, 360)
      const dy = (e.clientY - (r.top + r.height * 0.6)) / Math.max(r.height, 360)
      const clamp = (n: number) => Math.max(-1, Math.min(1, n))
      el.style.setProperty("--px", `${clamp(dx * 2.2) * 4}px`)
      el.style.setProperty("--py", `${clamp(dy * 2.2) * 3.5}px`)
    }
    window.addEventListener("pointermove", on)
    window.addEventListener("pointerdown", on)
    return () => {
      window.removeEventListener("pointermove", on)
      window.removeEventListener("pointerdown", on)
    }
  }, [ref])
}

function Actions() {
  const waitlist = useWaitlist()
  return (
    <div className="cs-actions">
      <button type="button" className="cs-btn" onClick={(e) => waitlist.open(e.currentTarget)}>
        Join the waitlist
      </button>
      <Link className="cs-link" to="/">
        Back to the landing page
      </Link>
    </div>
  )
}

function Screen() {
  const ref = useRef<HTMLDivElement>(null)
  useTrack(ref)
  const [i, setI] = useState(0)
  const [pop, setPop] = useState<number | null>(null)
  useEffect(() => {
    const previous = document.title
    document.title = "Coming soon | Lemely"
    return () => {
      document.title = previous
    }
  }, [])
  return (
    <div className="marketing-brand cs-page" data-screen="coming-soon">
      <header className="cs-head">
        <Link to="/" aria-label="Lemely, back to the landing page">
          <BrandLockup size="sm" casing="lower" as="span" />
        </Link>
      </header>
      <main className="cs-main" tabIndex={-1}>
        <div className="cs-layout">
          <div className="cs-copy">
            <h1 className="cs-title">Almost ready. Say hi.</h1>
            <p className="cs-body">
              The Lemely app is coming soon. Join the waitlist and we’ll email you when it opens.
            </p>
            <Actions />
            <div className="cs-team-row">
              <Link className="cs-team" to={TEAM_SIGN_IN_PATH}>
                Team sign-in
              </Link>
              <Link className="cs-team" to={TEAM_SIGN_UP_PATH}>
                Team sign-up
              </Link>
            </div>
          </div>
          <div className="cs-peek" ref={ref}>
            {pop === null ? (
              <span className="cs-bubble" aria-hidden="true">
                Tap me.
              </span>
            ) : null}
            <button
              type="button"
              className="cs-peek-btn"
              data-pop={pop === null ? undefined : pop % 2}
              aria-label="Say hi to Binny"
              onClick={() => {
                setI((n) => (n + 1) % PEEK_CYCLE.length)
                setPop((n) => (n === null ? 0 : n + 1))
              }}
            >
              <span className="cs-crop">
                <Binny mood={PEEK_CYCLE[i]} className="cs-binny" />
              </span>
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}

/**
 * The pre-launch screen shown instead of the sign-in and signup forms while access is
 * restricted, and after a session is refused with 403 `access_restricted`. Own
 * `WaitlistProvider` because these routes sit outside the marketing frame.
 */
export function ComingSoon() {
  return (
    <WaitlistProvider>
      <Screen />
    </WaitlistProvider>
  )
}
