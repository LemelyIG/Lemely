import { lazy, Suspense } from "react"
import { RouteFallback } from "@/components/ui/state-views"
import type { RouteObject } from "react-router-dom"
import { Navigate } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"
import { parentRoute } from "@/portals/parent"
import { marketingRoute, MarketingLanding } from "@/portals/marketing"
import { platformAdminRoute, schoolAdminRoute } from "@/portals/admin"
import { useAuth } from "@/lib/auth/AuthContext"
import { RequireAuth, portalPathForRole } from "@/lib/auth/RequireAuth"
import { DEFAULT_TITLE, DEFAULT_DESCRIPTION } from "@/lib/meta/documentMeta"
import type { PageMeta } from "@/lib/meta/documentMeta"
/*
 * P3.1 (DECISION D1.4). Deliberately a static import, unlike every screen in
 * this file, which are all `React.lazy`.
 *
 * This component is the router's `errorElement`, so one of the two things it
 * exists to survive is a failed chunk load. A lazily-loaded error screen has
 * to fetch a chunk from the same origin that just failed to serve one, and
 * when that fetch fails too there is nothing left to render the failure with.
 * It is a small screen, and it is the one worth carrying in the entry bundle.
 */
import { NotFound } from "@/portals/misc/NotFound"

/*
 * One role-based app. The Teacher (teal), Student (terracotta) and Parent
 * (muted rose) portals are route subtrees, each owning its own layout, nav and
 * screens. The active portal sets data-portal on its layout root so the token
 * layer swaps accent + neutrals (see index.css).
 *
 * Every portal subtree is gated by RequireAuth: no session -> /login; wrong
 * role for the portal -> the portal that does match. Root "/" and both login
 * routes resolve against the session too (see Root/LoginRoute below).
 */

// P6.1b: these four top-level screens sit outside any portal layout (no
// shared chrome to keep painted around them, unlike the three portals below,
// which each wrap their own Outlet in one Suspense boundary — see e.g.
// `portals/student/index.tsx`). With no shared wrapper to hang a single
// boundary off, each lazy element gets its own inline `<Suspense>` at the
// route definition instead of one boundary around the whole router tree —
// that keeps a slow-loading DeviceSettings chunk from blanking an
// already-rendered Login screen if a session is mid-navigation between them.
const Login = lazy(() => import("@/portals/auth/Login").then((m) => ({ default: m.Login })))
const ParentLogin = lazy(() =>
  import("@/portals/auth/ParentLogin").then((m) => ({ default: m.ParentLogin })),
)
const DeviceSettings = lazy(() =>
  import("@/portals/settings/DeviceSettings").then((m) => ({ default: m.DeviceSettings })),
)
const NotificationSettings = lazy(() =>
  import("@/portals/settings/NotificationSettings").then((m) => ({
    default: m.NotificationSettings,
  })),
)


const STUDENT_ROLES = ["student"] as const
const PARENT_ROLES = ["parent"] as const
/*
 * `parent` was in this list until P3.9 — every /api/teacher/* route is gated
 * teacher+school_admin, so a parent who signed in landed in a console where
 * every panel 403'd.
 *
 * P4.7 removed `platform_admin` for a related but distinct reason, and the
 * distinction is this surface's headline. The two admin roles were bundled
 * here as though they were alike. They are not:
 *
 * * `school_admin` genuinely holds this API's data. `require_role` admits them
 *   on every /api/teacher/* route, and the services then scope them to the
 *   schools they hold a membership for — so marking review, class analytics
 *   and school-wide announcements really do work for them. They stay, and
 *   `/school` is their home rather than their boundary.
 * * `platform_admin` holds none of it, by design. Every one of those same
 *   services returns **empty** for them: "no super-role bypass" (D1.6/D1.10),
 *   stated outright in `class_repo.py`, `review.py`, `teacher.py` and
 *   `at_risk_repo.py`. So this portal could only ever have shown them a
 *   console where every panel was correctly, permanently blank — which is
 *   indistinguishable on screen from a broken one.
 */
const TEACHER_ROLES = ["teacher", "school_admin"] as const
/* K-01…K-04. A school admin may reach both this and the teacher portal. */
const SCHOOL_ADMIN_ROLES = ["school_admin"] as const
/* X-01…X-03. The only subtree a platform admin can reach besides /settings. */
const PLATFORM_ADMIN_ROLES = ["platform_admin"] as const
/* G-11 is "All" in the UI spec, and the device limit is enforced per account
 * regardless of role, so its guard admits every role and only excludes callers
 * with no session at all. */
const ALL_ROLES = [
  ...STUDENT_ROLES,
  ...PARENT_ROLES,
  ...TEACHER_ROLES,
  ...PLATFORM_ADMIN_ROLES,
] as const

/*
 * P4.9 (surface 9). `/` used to send a signed-out visitor to `/login`, which
 * meant the product had **no public page at all** — the marketing page was
 * mounted inside the student portal behind `RequireAuth allowedRoles={
 * ["student"]}`, so the only reader who could reach it was a student who had
 * already signed up. See the header of `portals/marketing/index.tsx` for the
 * full account; it is that surface's headline finding.
 *
 * A signed-out visitor now gets the landing page. A signed-in one still goes
 * straight to their portal, which is the behaviour that was worth keeping:
 * for someone with a session, `/` is a bookmark to their dashboard, not an
 * advert for a product they already use.
 *
 * `MarketingLanding` is rendered rather than redirected to, so a first-time
 * visitor's first paint is the page itself and not a second navigation.
 */
function Root() {
  const { session } = useAuth()
  if (!session) return <MarketingLanding />
  return <Navigate to={portalPathForRole(session.role)} replace />
}

function LoginRoute({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  if (session) return <Navigate to={portalPathForRole(session.role)} replace />
  return children
}

/*
 * P3.1 (DECISION D1.4) · error handling at the route level.
 *
 * `errorElement` is set on each top-level route rather than once on a wrapper,
 * because react-router bubbles a thrown error to the nearest ancestor route
 * that declares one — and with no `errorElement` anywhere it falls back to its
 * own built-in screen: unstyled black-on-white, "Unexpected Application
 * Error!", a stack trace, no layout and no route back. That was the product's
 * real behaviour on any render error before this.
 *
 * This complements rather than replaces `ErrorBoundary` (C-14, Phase 2). The
 * two catch different things at different granularities: `ErrorBoundary` is
 * placed *inside* a screen so one broken widget degrades to a panel while the
 * rest of the page keeps working, and Phase 4 places those as it rebuilds each
 * surface. This is the backstop for everything that escapes them, including
 * errors thrown by a route's own element before any inner boundary mounts.
 */
const errorElement = <NotFound />

/*
 * The route table, exported as a plain value.
 *
 * P4.9 split this out of `App.tsx`, which built the router at module scope.
 * `createBrowserRouter` touches `document` on import, so any test that wanted
 * to make an assertion about the product's routing had to run in jsdom — and
 * `vitest.config.ts` runs the node environment on purpose ("a decision, not a
 * default"). The practical consequence was that routing facts could only be
 * checked by reading this file as *text*, which is how the marketing page
 * spent the whole build mounted behind a student-only auth guard with every
 * gate green (see `portals/marketing/index.tsx`).
 *
 * The array is the thing worth asserting on. `App.tsx` now does nothing but
 * hand it to the router.
 */
/*
 * P6.5 · page metadata for the top-level routes.
 *
 * These four are the only routes in the product a signed-out reader can reach,
 * so they are the only ones that carry a `description` (the module note in
 * `lib/meta/documentMeta.ts` explains why the authenticated screens do not).
 * Everything behind `RequireAuth` gets a title only.
 *
 * The descriptions describe the screen and claim nothing about the product that
 * the product does not do (§3.2 item 10).
 */
const rootMeta: PageMeta = { title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION }

export const appRoutes: RouteObject[] = [
  { path: "/", element: <Root />, errorElement, handle: rootMeta },
  /*
   * The public marketing lane. Deliberately NOT wrapped in `RequireAuth` — the
   * whole subtree is public, which is the point of it existing (P4.9).
   *
   * `/landing` is the stable path: existing links, `scripts/audit.mjs` and the
   * capture harness address it without depending on session state, and
   * `/student/landing` redirects here.
   */
  { ...marketingRoute, path: "/landing", errorElement },
  {
    path: "/login",
    errorElement,
    handle: {
      title: "Sign in",
      description:
        "Sign in to Lemely to mark a past paper, review a class, or follow a child's progress.",
    } satisfies PageMeta,
    element: <LoginRoute><Suspense fallback={<RouteFallback className="p-8" />}><Login /></Suspense></LoginRoute>,
  },
  // G-05. A separate route rather than a tab on /login: the parent flow shares
  // no field with email/password, and the spec's whole framing for it is
  // "the lowest-friction entry in the product".
  {
    path: "/login/parent",
    errorElement,
    handle: {
      title: "Parent sign in",
      /*
       * "a one-time code", not "a code sent by text", and the difference is
       * load-bearing. The screen itself says "we'll text you a code" — and
       * `lemely/web/deps.py` wires `sms=MockSmsProvider()` unconditionally,
       * with no config switch, and `MockSmsProvider.send_code` *logs* the code
       * rather than sending it. `SmsProvider` even documents a
       * `delivers_out_of_band` flag that "any real provider added later must
       * set True", i.e. none exists.
       *
       * So no deployment of this code as written can send an SMS. The screen's
       * claim is a pre-existing defect recorded in D6.9 for the human, not
       * something to fix from a route table. What this description will not do
       * is carry the claim into a second file, and into the one place a
       * scraper would index it. The OTP itself is real, so that is what it
       * says.
       */
      description:
        "Parents sign in to Lemely with a phone number and a one-time code. No password to set up.",
    } satisfies PageMeta,
    element: (
      <LoginRoute>
        <Suspense fallback={<RouteFallback className="p-8" />}>
          <ParentLogin />
        </Suspense>
      </LoginRoute>
    ),
  },
  // G-11 (devices section). Top-level rather than inside a portal subtree: the
  // 3-device limit applies to every account, so all five roles reach the same
  // screen — the same reason `/api/me/devices` is role-agnostic (P5.7).
  {
    path: "/settings/devices",
    errorElement,
    handle: { title: "Your devices" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <Suspense fallback={<RouteFallback className="p-8" />}>
          <DeviceSettings />
        </Suspense>
      </RequireAuth>
    ),
  },
  // G-12. Top-level for the same reason, and one it does not share: the
  // at-risk-alert preference belongs to the **teacher and the parent**
  // (`routers/me.py` gates it to those two roles), so mounting this inside the
  // student portal would have put a toggle out of reach of the only roles it
  // applies to.
  {
    path: "/settings/notifications",
    errorElement,
    // "Notification settings", not "Notifications": the student portal has a
    // screen at /student/notifications that IS the reader's inbox, and two tabs
    // reading the same word is the defect this whole file is closing.
    handle: { title: "Notification settings" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <Suspense fallback={<RouteFallback className="p-8" />}>
          <NotificationSettings />
        </Suspense>
      </RequireAuth>
    ),
  },
  {
    ...teacherRoute,
    errorElement,
    element: <RequireAuth allowedRoles={TEACHER_ROLES}>{teacherRoute.element}</RequireAuth>,
  },
  // P4.7 (D1.6). Two subtrees rather than one `/admin`, because they are two
  // different jobs held by two different roles with no overlapping screen
  // between them, and one guard per subtree is a guard a test can assert in
  // both directions (see `tests/unit/adminRoutes.test.ts`).
  {
    ...schoolAdminRoute,
    errorElement,
    element: (
      <RequireAuth allowedRoles={SCHOOL_ADMIN_ROLES}>{schoolAdminRoute.element}</RequireAuth>
    ),
  },
  {
    ...platformAdminRoute,
    errorElement,
    element: (
      <RequireAuth allowedRoles={PLATFORM_ADMIN_ROLES}>{platformAdminRoute.element}</RequireAuth>
    ),
  },
  {
    ...studentRoute,
    errorElement,
    element: <RequireAuth allowedRoles={STUDENT_ROLES}>{studentRoute.element}</RequireAuth>,
  },
  {
    ...parentRoute,
    errorElement,
    element: <RequireAuth allowedRoles={PARENT_ROLES}>{parentRoute.element}</RequireAuth>,
  },
  /*
   * Catch-all, last so it only matches what nothing above did.
   *
   * It is deliberately NOT gated by `RequireAuth`. A mistyped URL from a
   * signed-out reader is a 404, not a login prompt: bouncing them to `/login`
   * to then land somewhere that still is not the page they asked for is two
   * wrong answers instead of one. `NotFound` reads the session itself and
   * offers sign-in or the reader's own dashboard accordingly.
   *
   * Note this also catches unmatched paths *within* a portal subtree
   * (`/student/nonsense`), because the portal routes above enumerate their
   * children and match none of them. Those land here rather than on a
   * portal-shaped 404, which is a known simplification: a 404 inside the
   * student portal loses the sidebar. Rebuilding it as a per-portal child
   * route is Phase 4 work, once each portal layout is its final shape.
   */
  {
    path: "*",
    element: <NotFound />,
    errorElement,
    // Public, because this is the route a stale external link lands on, and it
    // is the one page in the product whose description a scraper is likely to
    // read by accident. It says what the page is, not what the product is.
    handle: {
      title: "Page not found",
      description: "This Lemely page does not exist. The link may be out of date.",
    } satisfies PageMeta,
  },
]
