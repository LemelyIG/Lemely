import { lazy, Suspense } from "react"
import { RouteFallback } from "@/components/ui/state-views"
import type { RouteObject } from "react-router-dom"
import { Navigate, useSearchParams } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"
import { parentRoute } from "@/portals/parent"
import { marketingRoute, dataHandlingRoute, MarketingLanding } from "@/portals/marketing"
import { platformAdminRoute, schoolAdminRoute } from "@/portals/admin"
import { useAuth } from "@/lib/auth/AuthContext"
import { RequireAuth, portalPathForRole } from "@/lib/auth/RequireAuth"
import { DEFAULT_TITLE, DEFAULT_DESCRIPTION } from "@/lib/meta/documentMeta"
import type { PageMeta } from "@/lib/meta/documentMeta"
import { safeNextPath } from "@/lib/nextPath"
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
 * PR 2 part A2. Static for the identical reason `NotFound` above is: this is
 * the router's `errorElement`, so a lazy import of it would have to fetch a
 * chunk from the same origin a chunk-load failure has already shown cannot be
 * trusted — including the failure this exact screen exists to classify as
 * `new-version` and recover from.
 */
import { RouteErrorScreen } from "@/components/route-error"
/*
 * `/session-ended` (below) is where `RequireAuth` sends a dead session before
 * it has rendered a single portal chunk — the same reasoning, and the same
 * "static, not lazy" answer, as the two imports above.
 */
import { SessionEnded } from "@/portals/misc/SessionEnded"

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
const ProfileSettings = lazy(() =>
  import("@/portals/settings/ProfileSettings").then((m) => ({ default: m.ProfileSettings })),
)

/*
 * Task 19 (spec §4.4) · lazy consts for the five G-02/G-03/G-06/G-07/G-08
 * screens (SignupRoleSelect.tsx, SignupDetails.tsx, VerifyEmail.tsx,
 * PasswordReset.tsx, JoinWithCode.tsx), built and committed ahead of this
 * file and unreachable until something registers a route for them. Six
 * consts rather than five, because `/reset` and `/reset/:token` are two
 * screens exported from one module (`PasswordResetRequest`/
 * `PasswordResetConfirm`, Task 17's "two routes, two views each") while
 * `/signup/student` and `/signup/teacher` go the other way: one component,
 * `SignupDetails`, taking `role` as a prop the route supplies rather than
 * two files (see that component's own module docstring). Likewise
 * `VerifyEmail` and `JoinWithCode` each back two routes on their own,
 * reading the optional route param themselves.
 *
 * Same P6.1b reasoning as the four above, and the same consequence below:
 * each gets its own inline `<Suspense>` at its route definition rather than
 * a shared boundary, because there is still no portal layout here to hang
 * one off. A first-time visitor moving from `/signup` to `/signup/student`
 * on a slow connection should not have the role-select screen it already
 * painted go blank while the details screen's chunk loads in behind it.
 */
const SignupRoleSelect = lazy(() =>
  import("@/portals/auth/SignupRoleSelect").then((m) => ({ default: m.SignupRoleSelect })),
)
const SignupDetails = lazy(() =>
  import("@/portals/auth/SignupDetails").then((m) => ({ default: m.SignupDetails })),
)
const VerifyEmail = lazy(() =>
  import("@/portals/auth/VerifyEmail").then((m) => ({ default: m.VerifyEmail })),
)
const PasswordResetRequest = lazy(() =>
  import("@/portals/auth/PasswordReset").then((m) => ({ default: m.PasswordResetRequest })),
)
const PasswordResetConfirm = lazy(() =>
  import("@/portals/auth/PasswordReset").then((m) => ({ default: m.PasswordResetConfirm })),
)
const JoinWithCode = lazy(() =>
  import("@/portals/auth/JoinWithCode").then((m) => ({ default: m.JoinWithCode })),
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

/**
 * Guards `/session-ended` against a reader who already has a live session
 * (adversarial review NIT, PR 2). Not `LoginRoute` reused verbatim: that one
 * always lands a signed-in visitor on their portal root, but `/session-ended`
 * can carry its own validated `?next=`, and a signed-in reader who followed
 * one here should land on what it names instead of being sent to the root
 * regardless — `next` was where they were headed before whatever routed them
 * through this screen.
 */
function SessionEndedRoute({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  const [searchParams] = useSearchParams()
  if (!session) return children
  const next = safeNextPath(searchParams.get("next"))
  return <Navigate to={next ?? portalPathForRole(session.role)} replace />
}

/**
 * `/settings/*` predates the in-portal `/teacher/settings/*` and
 * `/student/settings/*` sections this same change adds. Both now exist, so a
 * student or teacher following an old top-level link (a bookmark, a stale
 * link elsewhere in the product) is sent on to the portal-scoped screen
 * instead of rendering the frame-only version here — the two render the same
 * sections, and the portal one carries the portal's own chrome around them.
 *
 * Parent and the two admin roles have no portal-scoped Settings section of
 * their own (P4.10's `SettingsFrame` remains their only route to it), so this
 * is a no-op for them and they keep rendering the framed screen exactly as
 * they always have.
 */
function SettingsLaneRedirect({
  segment,
  children,
}: {
  /** The path under a portal's own `settings` root: `""` for the profile
   * index, `"devices"` or `"notifications"` for its two siblings. */
  segment: "" | "devices" | "notifications"
  children: React.ReactNode
}) {
  const { session } = useAuth()
  const suffix = segment ? `/${segment}` : ""
  if (session?.role === "student") return <Navigate to={`/student/settings${suffix}`} replace />
  if (session?.role === "teacher") return <Navigate to={`/teacher/settings${suffix}`} replace />
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
 *
 * PR 2 part A2: the element itself is now `RouteErrorScreen`
 * (`components/route-error.tsx`), not the bare `NotFound` this constant used
 * to hold directly. `NotFound` still answers the identical "no error, or a
 * real 404" reading it always did — `RouteErrorScreen` reaches it by way of
 * `classifyRouteError`'s `not-found` variant — but every *other* row of that
 * classification table (offline, a stale build, a dropped session, a rate
 * limit, the marking service down) now renders through the same
 * `errorElement` too, instead of the generic "something went wrong at our
 * end" every non-404 used to fall back to regardless of what actually failed.
 */
const errorElement = <RouteErrorScreen />

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
 * `/`, `/login`, `/login/parent` and the `*` catch-all carried a `description`
 * here directly before Task 19; the nine routes spec §4.4 registers below join
 * them the same way. `/landing` and `/data` carry one too, spread in from route
 * objects `portals/marketing/index.tsx` defines, so they do not show up as a
 * `handle` literal in this file the way the rest do. Together this is the
 * entire list of routes a signed-out reader can reach in the product, and the
 * only ones that get a `description` (the module note in
 * `lib/meta/documentMeta.ts` explains why the authenticated screens do not).
 * Everything behind `RequireAuth` gets a title only.
 *
 * The descriptions describe the screen and claim nothing about the product
 * that the product does not do (§3.2 item 10) — and, for the nine below in
 * particular, never that a mail or a text was sent. `deps.py` wires
 * `MockEmailProvider` unconditionally, exactly as it already wires
 * `MockSmsProvider`, so no deployment of this code as written delivers
 * either. The comment on `/login/parent` below records that finding for the
 * SMS side in full; the nine descriptions below follow its lead rather than
 * re-arguing it.
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
  /*
   * P6.5 / D6.8. The footer's one legal-shaped link, and public for the same
   * reason the landing page is: the reader who most wants to know what happens
   * to a scan is the one deciding whether to upload a first one, and they do
   * not have an account yet.
   */
  { ...dataHandlingRoute, path: "/data", errorElement },
  {
    path: "/login",
    errorElement,
    handle: {
      title: "Sign in",
      description:
        "Sign in to Lemely to mark a past paper, review a class, or follow a child's progress.",
    } satisfies PageMeta,
    element: <LoginRoute><Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}><Login /></Suspense></LoginRoute>,
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
        <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
          <ParentLogin />
        </Suspense>
      </LoginRoute>
    ),
  },
  /*
   * PR 2 part A2 · `/session-ended`. `RequireAuth` sends a dead session here
   * (`lib/auth/RequireAuth.tsx`) instead of straight to `/login`, carrying
   * `?next=` so a successful sign-in returns the reader to what they were
   * doing. Not wrapped in `LoginRoute`: unlike the nine below, nothing here
   * mints a session, so there is no session-creating flow to protect a
   * signed-in visitor from re-entering by mistake.
   *
   * It is wrapped in `SessionEndedRoute`, though (adversarial review NIT) —
   * a *different* problem `LoginRoute` also exists for, just not the one its
   * own docstring is about. `RequireAuth` always clears a session before it
   * redirects here, so in the ordinary flow nobody with a live session ever
   * reaches this URL. A stale bookmark or a link followed after signing back
   * in some other way is the exception, and for that reader "Your session
   * ended" is simply false — they have one. `SessionEndedRoute` sends them on
   * instead of rendering the screen.
   */
  {
    path: "/session-ended",
    errorElement,
    handle: { title: "Your session ended" } satisfies PageMeta,
    element: (
      <SessionEndedRoute>
        <SessionEnded />
      </SessionEndedRoute>
    ),
  },
  /*
   * ────────────────────────────────────────────────────────────────────────
   * Task 19 (spec §4.4) · the nine signup/verify/reset/join routes.
   *
   * Five of the nine (`/signup`, `/signup/student`, `/signup/teacher`,
   * `/reset`, `/reset/:token`) are wrapped in `LoginRoute` exactly like
   * `/login` and `/login/parent` above: a signed-in visitor has an account
   * already and belongs back in their own portal rather than on a form for
   * creating one or recovering a password they can currently use.
   *
   * The other four (`/verify-email`, `/verify-email/:token`, `/join`,
   * `/join/:code`) are deliberately NOT wrapped — each carries its own
   * comment below saying why, because this is the exception in this block
   * most likely to look like an oversight to a future reader and get "fixed"
   * into a bug: wrapping either would make the screen unreachable for
   * exactly the signed-in account it is for.
   * ────────────────────────────────────────────────────────────────────────
   */
  // G-02. Role selection, the entry point for every self-service signup.
  {
    path: "/signup",
    errorElement,
    handle: {
      title: "Sign up",
      description:
        "Sign up for Lemely as a student or a teacher, and get started marking past papers.",
    } satisfies PageMeta,
    element: (
      <LoginRoute>
        <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
          <SignupRoleSelect />
        </Suspense>
      </LoginRoute>
    ),
  },
  /*
   * G-03's two variants are deliberately NOT wrapped in `LoginRoute`, and this
   * is the third exception in this file rather than an oversight.
   *
   * A successful signup mints a session — `AuthContext`'s `signup` sets it in
   * `onSuccess` — and the screen then routes to `/verify-email` itself, because
   * it is the only place that knows whether an invite code still has to be
   * redeemed first. Wrapping the route puts a guard in the tree that reads the
   * very session the form just created, and `LoginRoute` wins that race: it
   * renders `<Navigate to={portalPathForRole(...)}>` on the same commit, so the
   * screen's own `navigate("/verify-email")` is overridden before it is seen.
   *
   * The symptom was a new student landing on `/student/onboard` and G-07 being
   * unreachable on the happy path — a screen this product ships and, until the
   * E2E journeys ran for the first time, nobody could reach by signing up. Every
   * unit gate passed throughout: the route table is well-formed, the screen's
   * navigate call is correct in isolation, and the defect only exists once both
   * are mounted together with a real session.
   *
   * `/signup` above keeps its wrapper: role selection mints nothing, so bouncing
   * an already-signed-in visitor off it is right and cannot race anything.
   */
  // G-03, student variant. Two static paths rather than one route with a
  // `:role` segment (design spec §4.4's own choice) — see `SignupDetails.tsx`'s
  // module docstring for why that makes this the single source of truth for
  // which variant renders, not a `:role` param this file would have to parse.
  {
    path: "/signup/student",
    errorElement,
    handle: {
      title: "Student sign up",
      description:
        "Create a Lemely student account, upload a past paper, and see exactly what to study next.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <SignupDetails role="student" />
      </Suspense>
    ),
  },
  // G-03, teacher variant (D7.1, D7.2). The same `SignupDetails`, the other
  // `role`.
  {
    path: "/signup/teacher",
    errorElement,
    handle: {
      title: "Teacher sign up",
      description:
        "Create a Lemely teacher account and mark past papers faster, with partial credit worked out for you.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <SignupDetails role="teacher" />
      </Suspense>
    ),
  },
  /*
   * G-07, pending. NOT wrapped in `LoginRoute`, unlike every other route in
   * this block, and deliberately so: `VerifyEmail.tsx` itself is reachable
   * both signed out (`SignedOutPending`) and signed in (`SignedInPending`),
   * and a signed-in but unverified account is the ordinary case here, not an
   * edge one — it is exactly the account this screen exists for. Wrapping
   * this route would bounce that account straight back into its portal
   * before it ever saw a way to check its status or ask for the link again,
   * which is the "unreachable for the account that needs it" failure this
   * task exists to avoid. `VerifyEmail.tsx`'s own module docstring records
   * the identical reasoning from the component's side.
   */
  {
    path: "/verify-email",
    errorElement,
    handle: {
      title: "Verify your email",
      description:
        "Check whether a Lemely account's email address is verified. Everything except marking a paper stays open in the meantime.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <VerifyEmail />
      </Suspense>
    ),
  },
  // G-07, confirm. Same exception, same component: `VerifyEmail.tsx` reads
  // `useParams().token` itself to choose which of its two states to render,
  // the same "one component, two RouteObjects" shape `/login`/`/login/parent`
  // above already use. See the comment on `/verify-email` for why neither of
  // this pair is wrapped.
  {
    path: "/verify-email/:token",
    errorElement,
    handle: {
      title: "Confirm your email",
      description:
        "Confirm a Lemely account's email address from a verification link, then continue into the app.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <VerifyEmail />
      </Suspense>
    ),
  },
  // G-06, request. Wrapped in `LoginRoute`: unlike verification, a password
  // reset has nothing for a signed-in visitor to do here, since they can
  // already sign in with the password they have. `AuthContext.tsx`'s own note
  // on `confirmPasswordReset` records that this route is never reachable with
  // a session in the first place, for exactly this reason.
  {
    path: "/reset",
    errorElement,
    handle: {
      title: "Reset your password",
      description: "Request a password reset for a Lemely account by email address.",
    } satisfies PageMeta,
    element: (
      <LoginRoute>
        <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
          <PasswordResetRequest />
        </Suspense>
      </LoginRoute>
    ),
  },
  // G-06, set a new password. Same wrapping, same reasoning; the other half
  // of the "two routes, two views each" shape `PasswordReset.tsx`'s module
  // docstring describes.
  {
    path: "/reset/:token",
    errorElement,
    handle: {
      title: "Set a new password",
      description:
        "Set a new password for a Lemely account from a reset link. Every device gets signed out once the change takes effect.",
    } satisfies PageMeta,
    element: (
      <LoginRoute>
        <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
          <PasswordResetConfirm />
        </Suspense>
      </LoginRoute>
    ),
  },
  /*
   * G-08, enter a code. NOT wrapped in `LoginRoute`, and for a different
   * reason than `/verify-email`'s: redeeming a class code while signed in is
   * not an edge case to tolerate but the ordinary path for D1.10's
   * seat/school-linking case, not only the fresh-signup one — a teacher can
   * hand a code to a student who already holds an account from a previous
   * class. `JoinWithCode.tsx`'s own module docstring carries the identical
   * reasoning; this comment exists so the same fact does not live only inside
   * the component that happens to get mounted here.
   */
  {
    path: "/join",
    errorElement,
    handle: {
      title: "Join with an invite code",
      description:
        "Enter an invite code from your school to see what it joins, before you redeem it or sign up to claim it.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <JoinWithCode />
      </Suspense>
    ),
  },
  // G-08, deep-linked preview. Same exception as `/join` above, same
  // component: `JoinWithCode.tsx` exports one route-level wrapper that reads
  // the optional `:code` param itself and hands it to the screen as both a
  // `key` and an initial value (see that export's own docstring for why a
  // `key` rather than a plain prop).
  {
    path: "/join/:code",
    errorElement,
    handle: {
      title: "Preview your invite",
      description: "Preview the class an invite code joins, then redeem it or sign up to claim it.",
    } satisfies PageMeta,
    element: (
      <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
        <JoinWithCode />
      </Suspense>
    ),
  },
  // G-11 (devices section). Top-level rather than inside a portal subtree: the
  // 3-device limit applies to every account, so all five roles reach the same
  // screen — the same reason `/api/me/devices` is role-agnostic (P5.7).
  //
  // Wrapped in `SettingsLaneRedirect`, inside `RequireAuth` rather than
  // outside it: a signed-out visitor still gets sent to `/login` first, and
  // only once there is a real session does it matter whether that session
  // belongs to a student or teacher with a portal-scoped Settings of their
  // own to be sent on to instead.
  {
    path: "/settings/devices",
    errorElement,
    handle: { title: "Your devices" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <SettingsLaneRedirect segment="devices">
          <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
            <DeviceSettings />
          </Suspense>
        </SettingsLaneRedirect>
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
        <SettingsLaneRedirect segment="notifications">
          <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
            <NotificationSettings />
          </Suspense>
        </SettingsLaneRedirect>
      </RequireAuth>
    ),
  },
  // The third settings screen, added alongside the portal-scoped Settings
  // sections above. Top level for the same reason as its two siblings: parent
  // and the two admin roles have no portal Settings of their own to render
  // this inside, so `/settings/profile` stays their only route to it.
  {
    path: "/settings/profile",
    errorElement,
    handle: { title: "Profile settings" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <SettingsLaneRedirect segment="">
          <Suspense fallback={<RouteFallback className="p-8" frame="standalone" />}>
            <ProfileSettings />
          </Suspense>
        </SettingsLaneRedirect>
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
