/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect } from "react"
import { Link } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import type { BinnyMood } from "@/portals/marketing/Binny"
import { WaitlistProvider, useWaitlist } from "@/portals/marketing/waitlist/WaitlistDialog"
import "@/portals/marketing/brand-tokens.css"
import "./coming-soon.css"

import { PeekBinny } from "./PeekBinny"
import { TEAM_SIGN_IN_PATH, TEAM_SIGN_UP_PATH } from "./team"

const PEEK_CYCLE: BinnyMood[] = ["open", "happy", "wink", "thinking"]

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
          <PeekBinny moods={PEEK_CYCLE} bubble="Tap me." label="Say hi to Binny" />
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
