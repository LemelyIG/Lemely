/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { useStudentProfile } from "@/lib/hooks/useMeApi"
import { prefetchOnIntent } from "@/lib/prefetchOnIntent"
import { STUDENT_SETTINGS_TABS } from "@/portals/settings/settingsTabs"
import { StudentShell, STUDENT_SETTINGS_BASE } from "./shell"

export { STUDENT_BOTTOM_TABS } from "./shell"

/*
 * Student portal (terracotta). `StudentShell` (`./shell.tsx`) puts every
 * screen inside the shared design A shell (`components/shell/PortalShell`):
 * sidebar with the subject tree, floating top bar, phone tab bar. The shell
 * root sets data-portal="student" so the token layer resolves to the
 * terracotta accent + neutrals (student is also the default scope).
 *
 * P6.1b: every screen below is `React.lazy`, not a static import. This portal
 * alone pulled in ~24 screens' worth of JS (subject drilldowns, the whole
 * practice/placement/flashcards/studyplan flow) into the ONE bundle every
 * route paid for, regardless of which screen a session actually visited.
 * Splitting at the screen boundary means a student who only ever opens
 * Overview and Subject never downloads QuizBuilder-sized code they'll never
 * run. Screens are named exports (not default), so each lazy import needs the
 * `.then((m) => ({ default: m.X }))` adapter — `React.lazy` only accepts a
 * default-export module.
 */
const Overview = lazy(() => import("./screens/Overview").then((m) => ({ default: m.Overview })))
const Subject = lazy(() => import("./screens/Subject").then((m) => ({ default: m.Subject })))
const AllPapers = lazy(() => import("./screens/AllPapers").then((m) => ({ default: m.AllPapers })))
const PaperResult = lazy(() => import("./screens/PaperResult").then((m) => ({ default: m.PaperResult })))
// Task 11 (B6c): `loadCorrectPaper` is a named loader, not inlined into
// `lazy(...)`, so `prefetchOnIntent` below can pass the exact same function
// React.lazy uses — hovering/focusing the CTA warms the same module cache
// entry the router's own Suspense boundary will read from on navigation.
const loadCorrectPaper = () =>
  import("./screens/CorrectPaper").then((m) => ({ default: m.CorrectPaper }))
const CorrectPaper = lazy(loadCorrectPaper)
// One shared fire-once gate across every call site below (Header CTA,
// BottomNav's "Correct" tab) — see `prefetchOnIntent`'s own doc comment for
// why this must be a single call, not one per site.
const prefetchCorrectPaper = prefetchOnIntent(loadCorrectPaper)
const StudyPlanSession = lazy(() =>
  import("./screens/studyplan/StudyPlanSession").then((m) => ({ default: m.StudyPlanSession })),
)
const StudyPlanWeek = lazy(() =>
  import("./screens/studyplan/StudyPlanWeek").then((m) => ({ default: m.StudyPlanWeek })),
)
const Standings = lazy(() => import("./screens/Standings").then((m) => ({ default: m.Standings })))
const StudentClasses = lazy(() =>
  import("./screens/Classes").then((m) => ({ default: m.StudentClasses })),
)
const Announcements = lazy(() =>
  import("./screens/Announcements").then((m) => ({ default: m.Announcements })),
)
const Notifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.Notifications })),
)
const Friends = lazy(() => import("./screens/Friends").then((m) => ({ default: m.Friends })))
// S-33, S-34, S-35 (tutor marketplace, T22).
const FindTutor = lazy(() =>
  import("./screens/tutoring/FindTutor").then((m) => ({ default: m.FindTutor })),
)
const TutorProfile = lazy(() =>
  import("./screens/tutoring/TutorProfile").then((m) => ({ default: m.TutorProfile })),
)
const BookSession = lazy(() =>
  import("./screens/tutoring/BookSession").then((m) => ({ default: m.BookSession })),
)
const Profile = lazy(() => import("./screens/Profile").then((m) => ({ default: m.Profile })))
const Onboarding = lazy(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding })))
const PlacementInvite = lazy(() =>
  import("./screens/placement/PlacementInvite").then((m) => ({ default: m.PlacementInvite })),
)
const PlacementTest = lazy(() =>
  import("./screens/placement/PlacementTest").then((m) => ({ default: m.PlacementTest })),
)
const PlacementResult = lazy(() =>
  import("./screens/placement/PlacementResult").then((m) => ({ default: m.PlacementResult })),
)
const SubjectEntry = lazy(() => import("./screens/SubjectEntry").then((m) => ({ default: m.SubjectEntry })))
const PracticeGenerator = lazy(() =>
  import("./screens/practice/PracticeGenerator").then((m) => ({ default: m.PracticeGenerator })),
)
const PracticeSet = lazy(() =>
  import("./screens/practice/PracticeSet").then((m) => ({ default: m.PracticeSet })),
)
const PracticeResult = lazy(() =>
  import("./screens/practice/PracticeResult").then((m) => ({ default: m.PracticeResult })),
)
const PracticePrint = lazy(() =>
  import("./screens/practice/PracticePrint").then((m) => ({ default: m.PracticePrint })),
)
const FlashcardDecks = lazy(() =>
  import("./screens/flashcards/FlashcardDecks").then((m) => ({ default: m.FlashcardDecks })),
)
const FlashcardReview = lazy(() =>
  import("./screens/flashcards/FlashcardReview").then((m) => ({ default: m.FlashcardReview })),
)
// The Landing screen left this portal in P4.9 (see the redirect below). Its
// lazy import went with it: a chunk nothing in this subtree renders is a
// chunk the build still emits and the router still resolves.
const Parents = lazy(() => import("./screens/Parents").then((m) => ({ default: m.Parents })))
const RecentlyDeleted = lazy(() =>
  import("./screens/RecentlyDeleted").then((m) => ({ default: m.RecentlyDeleted })),
)
// Tutoring marketplace, T23 (SPEC §d S-36, S-37, S-38).
const Sessions = lazy(() =>
  import("./screens/tutoring/Sessions").then((m) => ({ default: m.Sessions })),
)
const SessionDetail = lazy(() =>
  import("./screens/tutoring/SessionDetail").then((m) => ({ default: m.SessionDetail })),
)
const TutorAccess = lazy(() =>
  import("./screens/tutoring/TutorAccess").then((m) => ({ default: m.TutorAccess })),
)
// Settings' three screens mount here too, alongside every other lazy screen
// in this portal — see `data.ts`'s `navGroups` and the route registration
// below. Same shared components the teacher portal's Settings mounts, so the
// two cannot drift.
// Each imported from its own module rather than the `@/portals/settings`
// barrel: importing all four through one barrel module means a chunk
// containing any one of them pulls in the code for all four, defeating the
// per-screen splitting P6.1b's note above otherwise does. The barrel still
// exists for other consumers (its own header explains why) — this portal
// just does not use it for the lazy boundary.
const SettingsModalRoute = lazy(() =>
  import("@/portals/settings/SettingsModal").then((m) => ({ default: m.SettingsModalRoute })),
)
const ProfileSettingsSection = lazy(() =>
  import("@/portals/settings/ProfileSettings").then((m) => ({
    default: m.ProfileSettingsSection,
  })),
)
const AccountSettingsSection = lazy(() =>
  import("@/portals/settings/AccountSettings").then((m) => ({ default: m.AccountSettingsSection })),
)
const AppearanceSettingsSection = lazy(() =>
  import("@/portals/settings/AppearanceSettings").then((m) => ({
    default: m.AppearanceSettingsSection,
  })),
)
const NotificationSettingsSection = lazy(() =>
  import("@/portals/settings/NotificationSettings").then((m) => ({
    default: m.NotificationSettingsSection,
  })),
)
const InstallSettingsSection = lazy(() =>
  import("@/portals/settings/InstallSettings").then((m) => ({
    default: m.InstallSettingsSection,
  })),
)

/**
 * D7.9 — is a redirect to `/student/onboard` owed on this render?
 *
 * Pulled out of `StudentLayout` as a pure function, deliberately, rather than
 * left as inline branches against the raw query result. `vitest.config.ts`
 * runs this repo's unit suite under Node with no jsdom and no renderer
 * (D3.20), so nothing that requires mounting `StudentLayout` — a hook call, a
 * `<Suspense>` boundary, `useLocation()` itself — is reachable from a unit
 * test here. The *decision* the gate makes is reachable, once it is
 * something callable on its own, and that is the whole reason this function
 * exists rather than living as `if`s in the component:
 * `web/tests/unit/onboardingGate.test.ts` pins it directly, all four states.
 *
 * `status` is `useStudentProfile()`'s own three-way react-query status, not a
 * boolean the caller reduces it to first. That matters because the two
 * states that must NEVER redirect are exactly the two non-`"success"` ones,
 * and a caller left holding only `onboardingCompletedAt` cannot tell "not
 * answered yet" (`undefined`, mid-flight) apart from "answered no" (`null`,
 * resolved) — both look like "falsy" to a careless check. That conflation is
 * the specific failure D7.9's own risk register names: firing on `undefined`
 * bounces every returning student on every cold load, and firing on a fetch
 * error traps an account whenever `/me/student-profile` hiccups. Requiring
 * the real status up front makes both structurally impossible here, rather
 * than a discipline every call site has to keep separately.
 *
 * The third guard, `pathname === "/student/onboard"`, is what keeps this a
 * redirect and not a trap. The wizard finishes by calling
 * `useCompleteOnboarding()` and navigating away itself (see
 * `screens/Onboarding.tsx`'s `handleFinish`) — and until that mutation
 * resolves, the student is legitimately standing on the one screen this gate
 * would otherwise send them to, which must render, not bounce to itself.
 */
export type OnboardingProfileQueryStatus = "pending" | "error" | "success"

export function studentOnboardingRedirect(
  status: OnboardingProfileQueryStatus,
  onboardingCompletedAt: string | null,
  pathname: string,
): string | null {
  if (status !== "success") return null
  if (onboardingCompletedAt !== null) return null
  if (pathname === "/student/onboard") return null
  return "/student/onboard"
}

function StudentLayout() {
  const location = useLocation()
  // The S-02 record onboarding writes (`/me/student-profile`). A pending query
  // never redirects and shows the skeleton inside the shell.
  const studentProfile = useStudentProfile()
  const onboardingRedirect = studentOnboardingRedirect(
    studentProfile.status,
    studentProfile.data?.profile.onboardingCompletedAt ?? null,
    location.pathname,
  )
  if (onboardingRedirect) return <Navigate to={onboardingRedirect} replace />
  return (
    <StudentShell
      pending={studentProfile.isPending}
      prefetchCorrectPaper={prefetchCorrectPaper}
      overlay={{ routes: studentContentRoutes(), overlayBase: STUDENT_SETTINGS_BASE, fallbackPath: "/student" }}
    />
  )
}

export const studentRoute: RouteObject = {
  path: "student",
  element: <StudentLayout />,
  children: [
    /*
     * P6.5 · `handle.title` on every child.
     *
     * Titles name the SCREEN, never the record on it. A route table cannot know
     * which paper `result/:paperId` is showing, and reading the id back into
     * the tab ("Paper 4f3c9a...") would be worse than a general name. The
     * subject routes are the interesting case, because the code IS right there
     * in the path, and it still is not used: a title assembled from a URL
     * segment is a value restated from somewhere else, and P6.4's whole lesson
     * is what happens to those.
     */
    {
      index: true,
      element: <Overview />,
      handle: { title: "Dashboard", skeleton: "card-grid" },
    },
    {
      path: "classes",
      element: <StudentClasses />,
      handle: { title: "Your classes", skeleton: "card-grid" },
    },
    {
      path: "subject/:code",
      element: <Subject />,
      handle: { title: "Subject", skeleton: "page-header" },
    },
    {
      path: "subject/:code/papers",
      element: <AllPapers />,
      handle: { title: "All papers", skeleton: "page-header" },
    },
    {
      path: "result/:paperId",
      element: <PaperResult />,
      // The paper result slides like any page on phones (user decision, 2026-11-14), so it carries no
      // `viewTransition: false` marker. Desktop is unchanged: nothing there navigates here with a
      // view transition. The marker still works (`nativePushDefault` reads it) for a route that
      // needs to opt out. See DESIGN-study-notebook.md 9.4.
      handle: { title: "Paper result", skeleton: "page-header" },
    },
    {
      path: "correct",
      element: <CorrectPaper />,
      handle: { title: "Mark a paper", skeleton: "page-header", immersive: true },
    },
    // F1: the Plan tab's root. It redirects to the first subject's study plan; L9 swaps this element.
    {
      path: "plan",
      element: <SubjectEntry section="plan" />,
      handle: { title: "Study plan", skeleton: "page-header" },
    },
    {
      path: "plan/:subjectCode",
      element: <StudyPlanWeek />,
      handle: { title: "Study plan", skeleton: "page-header" },
    },
    {
      path: "plan/:subjectCode/session/:sessionId",
      element: <StudyPlanSession />,
      handle: { title: "Study session", skeleton: "page-header" },
    },
    {
      path: "board",
      element: <Standings />,
      handle: { title: "Leaderboard", skeleton: "list" },
    },
    {
      path: "announcements",
      element: <Announcements />,
      handle: { title: "Announcements", skeleton: "list" },
    },
    {
      path: "notifications",
      element: <Notifications />,
      handle: { title: "Notifications", skeleton: "list" },
    },
    { path: "friends", element: <Friends />, handle: { title: "Friends", skeleton: "list" } },
    // S-33, S-34, S-35 (tutor marketplace, T22).
    { path: "tutors", element: <FindTutor />, handle: { title: "Tutors", skeleton: "list" } },
    {
      path: "tutors/:tutorId",
      element: <TutorProfile />,
      handle: { title: "Tutor profile", skeleton: "page-header" },
    },
    {
      path: "tutors/:tutorId/book",
      element: <BookSession />,
      handle: { title: "Book a session", skeleton: "page-header" },
    },
    {
      path: "profile",
      element: <Profile />,
      handle: { title: "Your profile", skeleton: "page-header" },
    },
    // The only place a parent_child_links row is created (D3.11).
    {
      path: "parents",
      element: <Parents />,
      handle: { title: "Parent access", skeleton: "page-header" },
    },
    {
      path: "sessions",
      element: <Sessions />,
      handle: { title: "My sessions", skeleton: "list" },
    },
    {
      path: "sessions/:bookingId",
      element: <SessionDetail />,
      handle: { title: "Session details", skeleton: "page-header" },
    },
    {
      path: "tutor-access",
      element: <TutorAccess />,
      handle: { title: "Tutors & your data", skeleton: "list" },
    },
    {
      path: "recently-deleted",
      element: <RecentlyDeleted />,
      handle: { title: "Recently deleted", skeleton: "list" },
    },
    {
      // A dialog over the current page: PortalShell's ScreenOutlet overlay renders
      // the page underneath, this route renders the dialog. One child per entry in
      // STUDENT_SETTINGS_TABS; settingsTabs.test.ts holds the two in step.
      path: "settings",
      element: (
        <SettingsModalRoute
          tabs={STUDENT_SETTINGS_TABS}
          basePath={STUDENT_SETTINGS_BASE}
          fallbackPath="/student"
        />
      ),
      handle: { title: "Settings", skeleton: "page-header" },
      children: [
        {
          index: true,
          // Appearance has its own tab here, so not inside Profile.
          element: <ProfileSettingsSection appearance={false} />,
          handle: { title: "Profile settings", skeleton: "page-header" },
        },
        {
          path: "devices",
          element: <AccountSettingsSection />,
          handle: { title: "Account and devices", skeleton: "page-header" },
        },
        {
          path: "notifications",
          element: <NotificationSettingsSection />,
          handle: { title: "Notification settings", skeleton: "page-header" },
        },
        {
          path: "appearance",
          element: <AppearanceSettingsSection />,
          handle: { title: "Appearance", skeleton: "page-header" },
        },
        {
          path: "install",
          element: <InstallSettingsSection />,
          handle: { title: "Install Lemely", skeleton: "page-header" },
        },
      ],
    },
    {
      path: "onboard",
      element: <Onboarding />,
      handle: { title: "Getting set up", skeleton: "page-header" },
    },
    {
      path: "placement/:subjectCode",
      element: <PlacementInvite />,
      handle: { title: "Placement test", skeleton: "page-header" },
    },
    {
      path: "placement/test/:assignmentId",
      element: <PlacementTest />,
      handle: { title: "Placement test", skeleton: "page-header" },
    },
    {
      path: "placement/result/:assignmentId",
      element: <PlacementResult />,
      handle: { title: "Placement result", skeleton: "page-header" },
    },
    // F1: the Practice tab's root. L4 swaps this element for the Practice hub.
    {
      path: "practice",
      element: <SubjectEntry section="practice" />,
      handle: { title: "Practice", skeleton: "list" },
    },
    {
      path: "practice/:subjectCode",
      element: <PracticeGenerator />,
      handle: { title: "New practice set", skeleton: "page-header" },
    },
    {
      path: "practice/set/:assignmentId",
      element: <PracticeSet />,
      handle: { title: "Practice", skeleton: "page-header" },
    },
    {
      path: "practice/result/:assignmentId",
      element: <PracticeResult />,
      handle: { title: "Practice result", skeleton: "page-header" },
    },
    {
      path: "practice/print/:assignmentId",
      element: <PracticePrint />,
      handle: { title: "Print practice set", skeleton: "page-header" },
    },
    {
      path: "flashcards/:subjectCode",
      element: <FlashcardDecks />,
      handle: { title: "Flashcards", skeleton: "list" },
    },
    {
      path: "flashcards/review/:subjectCode",
      element: <FlashcardReview />,
      handle: { title: "Flashcard review", skeleton: "page-header" },
    },
    /*
     * P4.9 moved the marketing page out of this portal and onto a public
     * route. The path stays mounted, as a redirect, for three reasons that
     * each matter on their own: D1.1's explicit condition was that these
     * routes survive their nav entries; `tests/unit/navigation.test.ts`
     * asserts `/student/landing` is still a mounted, deep-linkable path; and
     * any link anyone has already saved should land on the page rather than
     * on a 404. `replace` so the redirect does not sit in the back stack.
     */
    // The handle is the landing page's own, not a name for the redirect: this
    // path resolves to `/landing` immediately, and a title is only ever read on
    // a page a reader is looking at.
    {
      path: "landing",
      element: <Navigate to="/landing" replace />,
      handle: { title: "Lemely", skeleton: "standalone" },
    },
    /*
     * P4.10. Last, so it only matches what nothing above did. Before this, an
     * unmatched path inside this portal fell through to the top-level `*` and
     * the reader lost the sidebar, the header and the trail on a typo. See
     * `portals/misc/NotFound.tsx` for why it is a separate component and not
     * the standalone screen.
     */
    {
      path: "*",
      element: <PortalNotFound />,
      handle: { title: "Page not found", skeleton: "page-header" },
    },
  ],
}

let contentRoutesCache: RouteObject[] | null = null

/** The portal's child routes minus the settings dialog, matched against the
 * page underneath while the dialog is open. Built on first use because
 * `studentRoute` is declared after the layout that reads it. */
function studentContentRoutes(): RouteObject[] {
  contentRoutesCache ??= (studentRoute.children ?? []).filter((route) => route.path !== "settings")
  return contentRoutesCache
}
