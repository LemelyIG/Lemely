/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, Suspense } from "react"
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom"
import { Gear, SignOut } from "@phosphor-icons/react"
import { useAuth } from "@/lib/auth/AuthContext"
import { useCachedChildSubject, useChildren } from "@/lib/hooks/useParentApi"
import { RouteFallback } from "@/components/ui/state-views"
import { Breadcrumbs, type Crumb } from "@/components/ui/breadcrumbs"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { PortalNotFound } from "@/portals/misc/NotFound"

// P6.1b: screens are `React.lazy`, not static imports — see the same note in
// `portals/student/index.tsx`. Only four screens here, but the parent portal
// still shipped every one of them (plus the other two portals') on first
// paint before this; the spec's own "two taps to the answer" goal is better
// served by that first paint being as small as possible.
const Children = lazy(() => import("./screens/Children").then((m) => ({ default: m.Children })))
const ChildOverview = lazy(() =>
  import("./screens/ChildOverview").then((m) => ({ default: m.ChildOverview })),
)
const SubjectDetail = lazy(() =>
  import("./screens/SubjectDetail").then((m) => ({ default: m.SubjectDetail })),
)
const Weaknesses = lazy(() => import("./screens/Weaknesses").then((m) => ({ default: m.Weaknesses })))

/*
 * Parent portal shell — the Study Notebook (P4.6, redesign surface 6).
 *
 * UI spec §4.8: "Total depth from login to the answer a parent came for: two
 * taps. Design for navigation depth and no interest in learning an interface."
 * So there is no sidebar and no nav list — the portal is four read-only screens
 * reached by tapping the thing you want to read. The only persistent control is
 * the child switcher, which the spec asks for explicitly ("If only one child,
 * skip straight to P-02 and keep this as a switcher in the header").
 *
 * The switcher is a native <select>: familiar, keyboard- and screen-reader-
 * complete for free, and nothing to learn. It shares `useChildren()`'s cache
 * with P-01, so mounting it costs no extra request.
 *
 * ── Container width, stated rather than left to drift ───────────────────────
 * DESIGN.md §13's container knob offers 680 (Read), 1200 (Operate) and 1280
 * (Persuade). This portal sits at 960px and stays there, which is none of
 * them, so it is recorded here rather than quietly kept. §2 puts parent views
 * in the Operate lane, and Operate's 1200px is measured *beside a 240–280px
 * sidebar*: it is the width of a content well, not of a whole page. This
 * portal has no sidebar by design, so 1200px edge-to-edge would set a
 * two-column stat row and a list of four subject rows across a span nothing on
 * the page is dense enough to fill. 960px is the same content well without the
 * sidebar in front of it. See DECISIONS D4.6.
 */

/** Child switcher (P-01's "keep this as a switcher in the header").
 *
 * Renders only when there is a child context to switch *within*: on a child
 * route, and only when the parent has more than one child. With one child
 * there is nothing to choose, and on the children list the page itself is the
 * switcher — a second copy in the header would be two controls for one job. */
function ChildSwitcher() {
  const { childId } = useParams<{ childId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { data } = useChildren()

  const children = data?.children ?? []
  if (!childId || children.length < 2) return null

  return (
    <label className="flex items-center gap-2 text-body-sm text-ink-muted">
      {/* The visible word is hidden at mobile for width, so the accessible
          name has to come from somewhere that is never hidden — otherwise the
          select is an unlabelled control below 640px. */}
      <span className="hidden sm:inline" aria-hidden="true">
        Viewing
      </span>
      <select
        aria-label="Choose which child to view"
        value={childId}
        onChange={(event) => {
          // Preserve where the parent is (overview / subject / weaknesses)
          // across the switch where the path still makes sense. A subject the
          // other child does not take would 404, so only the overview and
          // weaknesses tails carry over; everything else lands on the overview.
          const tail = location.pathname.endsWith("/weaknesses") ? "/weaknesses" : ""
          navigate(`/parent/children/${event.target.value}${tail}`)
        }}
        className="rounded-md border border-rule bg-paper-raised px-2.5 py-1.5 text-body-sm text-ink transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        {children.map((child) => (
          <option key={child.childId} value={child.childId}>
            {child.displayName}
          </option>
        ))}
      </select>
    </label>
  )
}

/**
 * P3.1 (DECISION D1.5) · the parent portal's way back — and, since P4.6, the
 * portal's *only* way back.
 *
 * The audit found no back affordance here, and this portal is the one where
 * that matters most: PRODUCT.md defines the parent as having "no interest in
 * learning an interface", the spec budgets two taps from login to the answer,
 * and two of the four screens are only reachable by drilling in from a third.
 *
 * ── What P4.6 changed, and why it counts as a defect rather than a tidy-up ──
 * P3.1 added this trail without removing the inline back links the three child
 * screens already carried, so every one of them shipped **two back
 * affordances, stacked, pointing at the same route**: the crumb row, and
 * immediately beneath it a "‹ Your children" (overview) or "‹ Back" (subject,
 * weak topics) link. Two controls in a column doing one job is not a redundant
 * convenience for this audience in particular — it reads as two different
 * places, and the reader has to spend a moment deciding which one is the real
 * one. The three inline links are gone; this row is what remains.
 *
 * The subtle part is the "Your children" crumb, which is conditional on the
 * parent having more than one child. `screens/Children.tsx` redirects
 * `/parent` straight to the child when there is exactly one — so for those
 * parents (the common case) a crumb pointing at `/parent` would land back on
 * the page they just left, which reads as a broken tap rather than a way back.
 * The same condition already governs `ChildSwitcher` above, and for the same
 * reason: with one child there is nothing to go back *to*.
 *
 * It shares `useChildren()`'s cache with the switcher and with P-01, so the
 * count costs no extra request. While the query is pending `children` is empty
 * and the crumb is simply omitted, which is the safe direction to be wrong in:
 * a missing crumb for one frame beats a crumb that leads somewhere circular.
 *
 * ── The subject crumb says the subject's name ───────────────────────────────
 * It used to read "This subject", a label that describes the page's *kind*
 * rather than the page, so a parent switching between two subject screens saw
 * an identical trail on both. `useCachedChildSubject` reads the entry the
 * screen below has already put in the react-query cache and never fetches, so
 * the name costs nothing; before it arrives the crumb falls back to the
 * syllabus code from the URL, which is the one thing the shell genuinely
 * knows. The code is the §4.8 design note's "secondary detail" rather than the
 * headline, and it appears here for at most the frame before the name does.
 */
function ParentTrail() {
  const location = useLocation()
  const { childId, code } = useParams<{ childId: string; code: string }>()
  const { data } = useChildren()
  const subject = useCachedChildSubject(childId ?? "", code ?? "")

  const hasChildList = (data?.children.length ?? 0) > 1
  if (!childId) return null

  const trail: Crumb[] = []
  if (hasChildList) trail.push({ label: "Your children", to: "/parent" })

  const childOverview = `/parent/children/${childId}`
  const path = location.pathname.replace(/\/+$/, "")

  if (path === childOverview) {
    trail.push({ label: "Overview" })
  } else if (path.endsWith("/weaknesses")) {
    trail.push({ label: "Overview", to: childOverview }, { label: "Weak topics" })
  } else if (/\/subjects\/[^/]+$/.test(path)) {
    trail.push(
      { label: "Overview", to: childOverview },
      { label: subject?.subjectName ?? code ?? "This subject" },
    )
  } else {
    trail.push({ label: "Overview", to: childOverview })
  }

  // One crumb is the current page's own name, which its heading already
  // carries. Rendering nothing beats rendering a row that repeats the <h1>.
  if (trail.length < 2) return null

  return <Breadcrumbs items={trail} className="py-3" />
}

/*
 * The real mark, replacing the accent-circle-with-an-italic-*l* that stood in
 * for it. That placeholder is audit finding M9 ("the logo is a lowercase
 * italic *l* in a filled circle, stamped in three places") and this was the
 * third and last stamp: the student sidebar's copy went with surface 1, the
 * teacher sidebar's with surface 5, and this one was still live. Three
 * surfaces in a row have now found a defect that was already fixed elsewhere,
 * which is the standing lesson rather than a coincidence.
 *
 * It was also this file's only `font-serif` call site — D4.1's defect, where
 * the class resolves to Tailwind's default Georgia stack, so the placeholder
 * was not even rendering in the display face it was reaching for.
 *
 * `alt=""` and `aria-hidden`, not a described image: the wordmark beside it
 * already says "Lemely", so describing the mark too makes a screen reader
 * announce the brand twice.
 */
function BrandLockup() {
  return (
    <>
      <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
      <span className="text-display-sm text-ink">Lemely</span>
    </>
  )
}

function Header() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="border-b border-rule bg-paper-raised">
      <div className="mx-auto flex w-full max-w-240 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 md:px-8">
        <Link
          to="/parent"
          className="flex items-center gap-2.5 rounded-md pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <BrandLockup />
        </Link>
        {/* `flex-wrap` on the row above and `min-w-0` here (P6.1). At the 320px
            viewport §6.1 requires, the brand lockup plus the child switcher,
            Settings and Sign out are wider than the 288px this row has between
            its own padding, and this cluster ran off the side of the screen in
            every state of the portal. It did not read as a layout bug either,
            because html and body clip rather than scroll: Sign out was simply
            not there, with nothing saying it existed. Wrapping costs a parent
            one row of height on the smallest phones and gives them back the
            only control that ends a session. */}
        <div className="ms-auto flex min-w-0 items-center gap-3">
          <ChildSwitcher />
          {/* The parent portal has no sidebar by design (P-01: "no interest in
              learning an interface"), so until P5.9 chunk D this header was the
              only surface that could reach G-11/G-12 and did not — a parent had
              no route to their own device list or to the at-risk-alert
              preference that is addressed to them. One entry, because the two
              settings screens link to each other. Same icon-at-mobile treatment
              as Sign out beside it, `aria-label` and all, for the same
              `button-name` reason. */}
          <Link
            to="/settings/devices"
            aria-label="Settings"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 pointer-coarse:min-h-11 pointer-coarse:min-w-11 pointer-coarse:justify-center text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            <Gear size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Settings</span>
          </Link>
          {/* The label collapses to an icon at mobile, so `aria-label` carries
              the accessible name at every width — without it axe reports a
              serious `button-name` violation below 640px (found in
              verification, not by the standing gates: audit.mjs is still
              scoped to the four student routes, D2.10 / P3.10 item (a)). */}
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => {
              logout()
              navigate("/login/parent", { replace: true })
            }}
            className="flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            <SignOut size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
    </header>
  )
}

// One boundary around the Outlet (not per-route): the header (logo, child
// switcher, settings, sign out) stays mounted and interactive while a screen
// chunk loads. Fallback is the shared `RouteFallback` (C-11 state-view
// family), same as the other two portals — see the student portal for why.

function ParentLayout() {
  // Only read here for `ErrorBoundary`'s `resetKey` below — `Header` and
  // `ParentTrail` each call `useLocation()` independently for their own
  // needs, but this component had no reason to before now.
  const location = useLocation()
  return (
    // `paper-grain` (DESIGN.md §8.1): one fixed, pointer-events-none noise
    // overlay at 0.03 opacity. The parent portal had no texture layer at all,
    // the same gap surface 5 found in the teacher portal, and it is the whole
    // mechanism by which §1's protected quality survives a screen made of
    // rows and numbers.
    <div data-portal="parent" className="paper-grain flex min-h-screen flex-col bg-paper">
      <SkipLink />
      <Header />
      {/* The trail sits between the header and `main` rather than inside it:
          it is wayfinding chrome, and putting it inside the skip link's target
          would mean skipping the navigation landed you on navigation. */}
      <div className="mx-auto w-full min-w-0 max-w-240 px-4 md:px-8">
        <ParentTrail />
      </div>
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto w-full min-w-0 max-w-240 flex-1 overflow-x-hidden px-4 pb-16 pt-2 focus:outline-none md:px-8"
      >
        <Suspense fallback={<RouteFallback />}>
          {/* PR 1B fulfils `routes.tsx`'s note ("Phase 4 places those as it
              rebuilds each surface") for this portal: a render crash in one
              screen stays inside this content slot rather than taking the
              header down with it or falling out to the top-level
              `errorElement`. Inside `Suspense` so a failed chunk load and a
              render throw both land in this boundary.
              `resetKey={location.pathname}` clears a caught error on
              navigation. */}
          <ErrorBoundary label="This page" resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </Suspense>
      </main>
    </div>
  )
}

export const parentRoute: RouteObject = {
  path: "parent",
  element: <ParentLayout />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    // "Your children" rather than a child's name: the route table has an id and
    // no name, and a parent with two children reads the same title on both
    // detail screens, which is the honest limit of what a static title knows.
    { index: true, element: <Children />, handle: { title: "Your children" } },
    { path: "children/:childId", element: <ChildOverview />, handle: { title: "Progress" } },
    {
      path: "children/:childId/subjects/:code",
      element: <SubjectDetail />,
      handle: { title: "Subject progress" },
    },
    {
      path: "children/:childId/weaknesses",
      element: <Weaknesses />,
      handle: { title: "Topics to work on" },
    },
    // P4.10. Last, so it only matches what nothing above did — an unmatched
    // path in this portal used to fall to the top-level `*` and cost the
    // reader the header and the child switcher. See `portals/misc/NotFound.tsx`.
    { path: "*", element: <PortalNotFound />, handle: { title: "Page not found" } },
  ],
}
