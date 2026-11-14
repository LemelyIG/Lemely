/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { lazy, Suspense, useEffect, useRef } from "react"
import { useLocation } from "react-router-dom"
import type { RouteObject } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { DEFAULT_TITLE, DEFAULT_DESCRIPTION } from "@/lib/meta/documentMeta"
import type { PageMeta } from "@/lib/meta/documentMeta"
import { MarketingHeader } from "./MarketingHeader"
import { MarketingFooter } from "./MarketingFooter"
import { WaitlistProvider } from "./waitlist/WaitlistDialog"
import "./marketing.css"
import "./brand-tokens.css"
import "./brand.css"

const Landing = lazy(() => import("./Landing").then(m => ({ default: m.Landing })))
const ConfirmEmail = lazy(() => import("./waitlist/ConfirmEmail").then(m => ({ default: m.ConfirmEmail })))
const DataHandling = lazy(() => import("./DataHandling").then(m => ({ default: m.DataHandling })))

/**
 * Scrolls to `location.hash` once the lazy page body exists. The browser's own
 * hash scroll runs before the chunk has mounted, so a deep link or a nav click
 * from `/` would otherwise stay at the top. Rendered inside the Suspense
 * boundary so it commits together with the page; later hash changes (nav
 * clicks, back and forward) re-run it via the router's location key.
 */
function HashScroll() {
  const { hash, key } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    const instant = first.current
    first.current = false
    if (!hash) return
    let id = hash.slice(1)
    try {
      id = decodeURIComponent(id)
    } catch {
      /* keep the raw id */
    }
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    let frame = 0
    let tries = 0
    const go = () => {
      const target = document.getElementById(id)
      if (target) {
        target.scrollIntoView({
          block: "start",
          behavior: instant || reduced ? "auto" : "smooth",
        })
        return
      }
      if (tries++ < 30) frame = requestAnimationFrame(go)
    }
    go()
    return () => cancelAnimationFrame(frame)
  }, [hash, key])
  return null
}

export function MarketingFrame({ children }: { children: React.ReactNode }) {
  /* No theme pin here: `<html data-theme>` is the one switch (anonymous visitors light, signed-in
     users their own choice, `lib/theme/theme.ts`), so the frame and every portal agree. */
  return <WaitlistProvider>
    <div className="marketing-brand min-h-dvh">
      <SkipLink />
      <MarketingHeader />
      <main id={MAIN_CONTENT_ID} tabIndex={-1}>{children}</main>
      <MarketingFooter />
    </div>
  </WaitlistProvider>
}

/**
 * Public marketing routes.
 *
 * `/landing` is the canonical path and `/` renders the same screen for a
 * signed-out visitor (`App.tsx`'s `Root`). Two paths rather than a redirect
 * from one to the other, because `/` must render immediately for a first-time
 * visitor rather than bouncing them through a second navigation, while
 * `/landing` is the stable path that existing links, the capture harness and
 * the audit script can address without depending on session state.
 */
export function MarketingLanding() {
  return (
    <MarketingFrame>
      {/*
        The fallback sits inside the frame, not around it, so the header and
        footer are painted on the first frame and only the page body waits on
        its chunk. A visitor arriving at `/` sees the mark immediately rather
        than a blank document, which for a first-time reader is the difference
        between a slow site and a broken one.
      */}
      <Suspense fallback={<RouteSkeleton />}>
        <Landing />
        <HashScroll />
      </Suspense>
    </MarketingFrame>
  )
}

export const marketingRoute: RouteObject = {
  path: "landing",
  element: <MarketingLanding />,
  /*
   * P6.5. The one page in the product that a search engine or a chat-app
   * unfurler can actually reach, so it carries the site's own title and
   * description rather than a page-specific one — `/` renders this same
   * component and both should read identically when shared.
   */
  handle: {
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    skeleton: "page-header",
  } satisfies PageMeta,
}

/**
 * The data page, in the same public frame as the landing page (P6.5, D6.8 A).
 *
 * In the marketing shell rather than standing alone because it is reached from
 * that shell's footer, and a reader who follows a footer link into a page with
 * no header has been dropped somewhere rather than taken somewhere: the way
 * back has to still be there.
 */
export function MarketingDataHandling() {
  return (
    <MarketingFrame>
      <Suspense fallback={<RouteSkeleton />}>
        <DataHandling />
        <HashScroll />
      </Suspense>
    </MarketingFrame>
  )
}

export const dataHandlingRoute: RouteObject = {
  path: "data",
  element: <MarketingDataHandling />,
  /*
   * The second of the product's two public content pages, so it carries its own
   * description rather than the site default: this is a page somebody may well
   * arrive at from a search for what the product does with a scan, and the
   * default description describes the marking product instead.
   *
   * The description states the page's subject and claims nothing further. In
   * particular it does not say "your data is safe", which is the sentence a
   * page like this is normally written to imply and the exact promise nothing
   * in this repository can support.
   */
  handle: {
    title: "How your data is handled",
    description:
      "What Lemely stores about an account, what happens to a paper you upload, where a scan is sent to be read, and who else can see your work.",
    skeleton: "page-header",
  } satisfies PageMeta,
}

/** The page the waitlist confirmation email links to. Public, in the marketing frame, never gated. */
export function MarketingWaitlistConfirm() {
  return (
    <MarketingFrame>
      <Suspense fallback={<RouteSkeleton />}>
        <ConfirmEmail />
      </Suspense>
    </MarketingFrame>
  )
}

export const waitlistConfirmRoute: RouteObject = {
  path: "waitlist/confirm",
  element: <MarketingWaitlistConfirm />,
  handle: {
    title: "Confirm your email",
    description: "Confirm your email address for the Lemely waitlist.",
    skeleton: "standalone",
  } satisfies PageMeta,
}

export { Landing, DataHandling }
