/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { lazy, Suspense } from "react"
import type { RouteObject } from "react-router-dom"
import { Link } from "react-router-dom"
import { RouteFallback } from "@/components/ui/state-views"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { DEFAULT_TITLE, DEFAULT_DESCRIPTION } from "@/lib/meta/documentMeta"
import type { PageMeta } from "@/lib/meta/documentMeta"

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
  return (
    <div className="paper-grain flex min-h-screen flex-col bg-paper">
      <SkipLink />
      <header className="sticky top-0 z-nav border-b border-rule bg-paper/85 backdrop-blur-nav">
        {/*
          The one permitted *kind* of `backdrop-blur` (§3.2 item 6): a page top
          bar, never scrolling content. `bg-paper/85` under it means the blur
          has something to lift, and text crossing beneath the header never
          reads through at full strength.

          P6.3 corrected two things this comment used to get wrong. It said
          "the one permitted backdrop-blur in the whole product", and there are
          four — this header and the student, teacher and admin shells — which
          is fine under the rule but is not what the sentence claimed. And the
          four declared themselves two different ways: this one at
          `backdrop-blur-sm` (8px) and the other three at an arbitrary
          `backdrop-blur-[10px]`. All four are now `backdrop-blur-nav`, the
          only radius the exception is allowed to use.

          `z-nav`, not the `z-sticky` this carried. Four top bars doing one job
          declared two bands, and this was the odd one out, sitting in the band
          `table.tsx` reserves for sticky table headers.
        */}
        <div className="mx-auto flex w-full max-w-marketing items-center justify-between gap-4 px-page-mobile py-3.5 md:px-page-tablet lg:px-page-desktop">
          <Link
            to="/"
            className="flex items-center gap-2.5 rounded-md pointer-coarse:min-h-11 transition-colors hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          >
            {/* `alt=""` + `aria-hidden`: the wordmark beside it already says
                "Lemely", so describing the mark too announces it twice. Same
                reasoning as `AuthFrame`. */}
            <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
            <span className="text-display-sm text-ink">Lemely</span>
          </Link>
          <nav aria-label="Marketing" className="flex items-center gap-1.5">
            <Link
              to="/login"
              className="text-label rounded-md px-3 py-2 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-ink-muted transition-colors hover:bg-paper-sunk hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Sign in
            </Link>
            {/*
              Parents get their own entry in the header rather than a line in
              the footer. G-05's framing is that the phone-code route is "the
              lowest-friction entry in the product", and a parent who has been
              sent a link by a teacher arrives here, not at /login, where every
              field is a password field they were never given.

              It was `hidden sm:inline-flex` in the first draft, which hid it
              below 640px — on the phone, which is where a parent who was sent
              a link opens it, and the route whose whole selling point is that
              a phone number is the entire login. The same reasoning the brief
              applies to students ("students live on phones") applies harder
              here. Two short labels fit at 320px; both stay.
            */}
            <Link
              to="/login/parent"
              className="text-label rounded-md px-3 py-2 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-ink-muted transition-colors hover:bg-paper-sunk hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Parents
            </Link>
          </nav>
        </div>
      </header>

      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto flex w-full max-w-marketing flex-col gap-3 px-page-mobile py-8 text-body-sm text-ink-faint md:flex-row md:items-center md:justify-between md:px-page-tablet lg:px-page-desktop">
          <div className="flex items-center gap-2.5">
            <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-5 w-5 shrink-0" />
            <span>Lemely, marking for CAIE papers.</span>
          </div>
          {/*
            P6.5 closes this, and the comment that used to sit here is worth
            keeping in substance: there were no legal links and none were
            invented, because a footer link to a page that does not exist is the
            dead navigation the audit went looking for.
            What ships is ONE link, to a page that describes what the software
            actually does with a reader's data, and no terms of service. D6.8
            records why, and the short form is that facts about this product can
            be derived from this repository and promises cannot. A privacy
            policy and a ToS are mostly promises about an operator who is not in
            the code, so writing them here would be inventing content in the one
            category where invention has legal consequences.
            The label says "How your data is handled" rather than "Privacy",
            because "Privacy" is the word readers have learned to expect a
            policy behind, and this is deliberately not one.
          */}
          {/*
            A COLUMN below `sm`, and the adapt gate is why rather than taste.

            The row was three links wide once this one joined it, and at 320px
            the 276px of content box left after the page padding is not enough:
            "How your data is handled" wrapped onto two lines, and it pushed
            "Parent sign in" onto two as well. Six findings, and all six were
            caused by adding the third link — hallmark's mobile
            non-negotiable is that clickable text never wraps, because the
            second line is a strip of link that looks like body copy and a
            thumb aiming at it hits neither.

            Stacking gives each link the full width, so each is one line and
            each is a full-width target. `items-start` rather than `items-end`:
            the labels then share the left edge with the brand line above them
            and the page's own margin, instead of forming a third ragged edge.
          */}
          <div className="flex flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-4">
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
              Sign in
            </Link>
            <Link
              to="/login/parent"
              className="rounded-sm underline-offset-4 pointer-coarse:inline-flex pointer-coarse:items-center pointer-coarse:justify-center pointer-coarse:min-h-11 pointer-coarse:min-w-11 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Parent sign in
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
