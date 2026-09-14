/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { lazy, Suspense, useRef } from "react"
import type { RouteObject } from "react-router-dom"
import { Link } from "react-router-dom"
import { BrandMark } from "@/components/ui/brand-mark"
import { buttonVariants } from "@/components/ui/button"
import { RouteFallback } from "@/components/ui/state-views"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { cn } from "@/lib/utils"
import { DEFAULT_TITLE, DEFAULT_DESCRIPTION } from "@/lib/meta/documentMeta"
import type { PageMeta } from "@/lib/meta/documentMeta"
import { useRevealFailsafe, useScrollProgress } from "./motion"
import "./marketing.css"

/*
 * ────────────────────────────────────────────────────────────────────────────
 * THE PERSUADE LANE, WHICH DID NOT EXIST
 * ────────────────────────────────────────────────────────────────────────────
 *
 * P4.9's headline. The marketing page was mounted at `/student/landing`, which
 * is inside `studentRoute`, which `App.tsx` wraps in
 * `RequireAuth allowedRoles={["student"]}`. Follow that through:
 *
 *   - a signed-out visitor, the entire audience of a marketing page, was
 *     redirected to `/login`;
 *   - a signed-in **teacher** was redirected to `/teacher`, so the page whose
 *     eyebrow reads "For CAIE teachers and their students" was unreachable by
 *     one of the two audiences it names;
 *   - `/` sent every signed-out visitor to `/login` as well, so the product
 *     had no public page of any kind;
 *   - and the only reader who could reach it, a signed-in student, is the one
 *     person on earth who does not need to be sold the product. They saw it
 *     wrapped in the app shell: sidebar, breadcrumb trail, streak pill, and a
 *     "Correct a paper" header CTA sitting above a hero that says "Mark a
 *     paper".
 *
 * The interesting part is that this was *known*. D1.1's note in
 * `portals/student/data.ts` calls it "the marketing page, orphaned inside the
 * authenticated app" and removes its nav entry, which fixed the symptom a
 * student saw and left the page with no reader at all. A route removed from
 * the nav is invisible; a route removed from the nav *and* behind an auth
 * guard for the wrong role is dead.
 *
 * So this is an IA change, of the kind REDESIGN-MISSION §1 explicitly permits
 * and §7 requires to be documented. The lane now has its own portal, its own
 * frame, and public routes. `/student/landing` stays mounted as a redirect
 * (see `portals/student/index.tsx`) so every existing deep link, the nav gate,
 * and `scripts/audit.mjs` all keep working.
 *
 * There is no `RequireAuth` anywhere in this file, deliberately. Everything in
 * this subtree is public by design, and the day something here is not, it
 * belongs in a portal rather than in the marketing shell.
 */

const Landing = lazy(() => import("./Landing").then((m) => ({ default: m.Landing })))
const DataHandling = lazy(() =>
  import("./DataHandling").then((m) => ({ default: m.DataHandling })),
)

/**
 * The public page frame: a slim header carrying the mark and the way in, the
 * page itself, and a footer.
 *
 * `AuthFrame` (`portals/auth/Login.tsx`) is the signed-out frame for the *auth*
 * screens and is deliberately not reused here. It centres a single card in the
 * viewport, which is right for a login form and wrong for a scrolling page with
 * six sections. The two share what actually matters, which is the token layer
 * and the paper grain, not a layout.
 *
 * Container is `--container-marketing` (1280px, DESIGN.md §13), one rung wider
 * than the app's 1200px well, because this lane has no sidebar taking 260px
 * out of the line length.
 */
export function MarketingFrame({ children }: { children: React.ReactNode }) {
  /*
   * The design's `.progress` bar (design-import-spec.md, page structure item
   * 1): a 2px accent hairline pinned to the nav's bottom edge, `scaleX`
   * driven by scroll progress. `useScrollProgress` is a no-op where the
   * browser supports `animation-timeline: scroll(root)` (`marketing.css`'s
   * own `@supports` block drives it); the ref only matters for the rAF
   * fallback. See `./motion.tsx` for why this isn't a scroll listener.
   */
  const progressRef = useRef<HTMLDivElement>(null)
  useScrollProgress(progressRef)
  /* The imported CSS's global reveal failsafe (design-import-spec.md, Motion
     utilities): mounted once, here, rather than per-section. */
  useRevealFailsafe()

  return (
    <div className="paper-grain flex min-h-dvh flex-col bg-paper">
      <SkipLink />
      {/*
        `.nav` (marketing.css) now owns the sticky positioning, z-index,
        border, background and blur that used to live here as Tailwind
        utilities (`sticky top-0 z-nav border-b border-rule bg-paper/85
        backdrop-blur-nav`) — the design is authoritative for this page's
        layout, and `.nav` is the verbatim port of it. `lm-app-header` and
        `lm-nav-chrome` stay: they are PWA/native concerns unrelated to this
        page's visual redesign — safe-area-inset-top padding in standalone
        mode, and suppressing the long-press callout on navigation chrome —
        and removing them would regress `feat/native-and-pwa`, the branch
        this one is built on.
      */}
      <header className="nav lm-app-header lm-nav-chrome">
        {/* `aria-hidden`: a reading-progress hairline, not information a
            screen-reader user needs announced — same treatment the design
            gives it (design-import-spec.md: "aria-hidden"). */}
        <div ref={progressRef} className="progress" aria-hidden="true" />
        <div className="wrap">
          <div className="nav__inner">
            <Link
              to="/"
              className="brand rounded-md pointer-coarse:min-h-11 transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            >
              {/* `BrandMark` sets its own `aria-hidden`: the wordmark beside
                  it already says "lemely", so describing the mark too
                  announces it twice. The wordmark text stays `sr-only` below
                  `sm` (640px) rather than `hidden`, for the same reason the
                  previous build gave: three header actions share the row
                  with it, and below 640px there is no room for the icon, the
                  word and three nav items on one line without wrapping a
                  label to two lines or forcing horizontal scroll, both hard
                  gates. A screen-reader user still hears the brand name even
                  though a sighted mobile reader sees only the mark. */}
              <BrandMark className="h-6 w-8 shrink-0" />
              {/* Lowercase "lemely": the design's own wordmark casing
                  (design-import-spec.md, page structure item 1 —
                  `.brand span` in display serif beside the mark). The
                  footer below keeps sentence case ("Lemely, marking for
                  CAIE papers.") because that is a sentence, not a
                  logotype; the two are not in tension. */}
              <span className="sr-only sm:not-sr-only sm:inline">lemely</span>
            </Link>
            <nav aria-label="Marketing" className="nav__links">
              <Link
                to="/login"
                className="rounded-md px-2 py-2 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 transition-colors hover:bg-paper-sunk focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:px-3"
              >
                Log in
              </Link>
              {/*
                Parents get their own entry in the header rather than a line
                in the footer. A parent account only ever comes from a
                child-issued invite, never from `/login` where every field
                asks for a credential they do not have yet, so this points at
                `/join` — the screen built for "I have a code" — exactly like
                `Login.tsx`'s own parent link and `SignupRoleSelect.tsx`'s
                parent card.
              */}
              <Link
                to="/join"
                className="rounded-md px-2 py-2 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 transition-colors hover:bg-paper-sunk focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:px-3"
              >
                Parents
              </Link>
              {/*
                `buttonVariants` rather than `<Button>`: this has to be a
                real `<Link>` (a signed-out visitor should be able to open it
                in a new tab, and a `<button onClick={navigate}>` takes that
                away), styled to match the kit exactly.
              */}
              {/* `nav__cta`: scopes `.nav__links a`'s muted-ink colour rule
                  (marketing.css) away from this one link — see that rule's
                  own comment for the contrast bug it fixes. */}
              <Link
                to="/signup"
                className={cn(buttonVariants({ variant: "primary", size: "sm" }), "nav__cta")}
              >
                Get started
              </Link>
            </nav>
          </div>
        </div>
      </header>

      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>

      <footer className="foot">
        <div className="wrap foot__inner text-body-sm text-ink-faint">
          <div className="flex items-center gap-2.5">
            <BrandMark className="h-5 w-7 shrink-0" />
            <span>Lemely, marking for CAIE papers.</span>
          </div>
          {/*
            ONE link to a page that describes what the software actually does
            with a reader's data, and no terms of service: a privacy policy
            and a ToS are mostly promises about an operator who is not in the
            code, so writing them here would be inventing content in the one
            category where invention has legal consequences. "How your data
            is handled" rather than "Privacy", because "Privacy" is the word
            readers have learned to expect a policy behind, and this is
            deliberately not one.
          */}
          <div className="foot__links">
            <Link
              to="/data"
              className="rounded-sm underline-offset-4 pointer-coarse:inline-flex pointer-coarse:items-center pointer-coarse:justify-center pointer-coarse:min-h-11 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              How your data is handled
            </Link>
            <Link
              to="/login"
              className="rounded-sm underline-offset-4 pointer-coarse:inline-flex pointer-coarse:items-center pointer-coarse:justify-center pointer-coarse:min-h-11 pointer-coarse:min-w-11 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Log in
            </Link>
            <Link
              to="/join"
              className="rounded-sm underline-offset-4 pointer-coarse:inline-flex pointer-coarse:items-center pointer-coarse:justify-center pointer-coarse:min-h-11 pointer-coarse:min-w-11 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Parent access
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
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
      <Suspense fallback={<RouteFallback className="px-page-mobile py-section" />}>
        <Landing />
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
  handle: { title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION } satisfies PageMeta,
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
      <Suspense fallback={<RouteFallback className="px-page-mobile py-section" />}>
        <DataHandling />
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
  } satisfies PageMeta,
}

export { Landing, DataHandling }
