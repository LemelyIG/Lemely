/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, type ReactNode } from "react"
import { Link, NavLink, useLocation } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  SealQuestion,
  ChartBar,
  Warning,
  Books,
  Sparkle,
  Gear,
  GraduationCap,
  Lifebuoy,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { gradeChipClass } from "@/lib/grade"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useReviewQueueCount } from "@/lib/hooks/useReviewQueueCount"
import { STAFF_INBOX_ERROR, TEACHER_INBOX_EMPTY, staffDestinationFor } from "@/lib/staffInbox"
import { navItems, resolveTrail, classesItemActive, type NavItem } from "./data"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { CreateSheet } from "./components/CreateSheet"
import { PortalShell } from "@/components/shell/PortalShell"
import { ShellIcon } from "@/components/shell/icons"
import { ShellUserBlock, type ShellSidebarContent } from "@/components/shell/ShellSidebar"
import { ShellNavList } from "@/components/shell/ShellNavList"
import { profileName } from "@/components/shell/ShellAvatar"
import { SHELL_BUTTON_PRIMARY, SHELL_BUTTON_TONAL } from "@/components/shell/shellStyles"
import {
  HELP_HREF,
  INBOX_TO,
  ANNOUNCEMENTS_TO,
  PROFILE_EDIT_TO,
  SETTINGS_TO,
  roleLabel,
} from "./components/topBarActions"
import type { AccountLink } from "@/components/shell/AccountPanel"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"
import { underlyingPathname } from "@/lib/nav/backgroundLocation"
import { TEACHER_SETTINGS_TABS } from "@/portals/settings/settingsTabs"

const TEACHER_SETTINGS_BASE = "/teacher/settings"

// P6.1b: screens are `React.lazy`, not static imports — see the same note in
// `portals/student/index.tsx`. QuizBuilder and ClassAnalytics in particular
// are heavy screens that most teacher sessions (grading, review) never open;
// they no longer ride along in the bundle every route pays for. Named
// exports (not default), hence the `.then((m) => ({ default: m.X }))` shape.
const Overview = lazy(() => import("./home/TeacherHome").then((m) => ({ default: m.TeacherHome })))
const Grading = lazy(() => import("./screens/Grading").then((m) => ({ default: m.Grading })))
const RecentlyDeleted = lazy(() =>
  import("./screens/RecentlyDeleted").then((m) => ({ default: m.RecentlyDeleted })),
)
const Review = lazy(() => import("./screens/Review").then((m) => ({ default: m.Review })))
const ReviewItem = lazy(() => import("./screens/ReviewItem").then((m) => ({ default: m.ReviewItem })))
const Classes = lazy(() => import("./screens/Classes").then((m) => ({ default: m.Classes })))
const ClassDetailLayout = lazy(() =>
  import("./screens/ClassDetail").then((m) => ({ default: m.ClassDetailLayout })),
)
const ClassRoster = lazy(() => import("./screens/ClassRoster").then((m) => ({ default: m.ClassRoster })))
const ClassAnalytics = lazy(() =>
  import("./screens/ClassAnalytics").then((m) => ({ default: m.ClassAnalytics })),
)
const ClassPapers = lazy(() =>
  import("./screens/ClassPapers").then((m) => ({ default: m.ClassPapers })),
)
// D7.10 / Task 21 — the create-first-class step the teacher setup screen
// (`home/TeacherSetup`) links to. Lazy for the same reason as every
// other screen here (P6.1b): most sessions, most of the time, never mount it.
const CreateFirstClass = lazy(() =>
  import("./screens/CreateFirstClass").then((m) => ({ default: m.CreateFirstClass })),
)
const StudentDetail = lazy(() =>
  import("./screens/StudentDetail").then((m) => ({ default: m.StudentDetail })),
)
const AtRiskList = lazy(() => import("./screens/AtRiskList").then((m) => ({ default: m.AtRiskList })))
const MarkSchemes = lazy(() => import("./screens/MarkSchemes").then((m) => ({ default: m.MarkSchemes })))
const Quizzes = lazy(() => import("./screens/Quizzes").then((m) => ({ default: m.Quizzes })))
const QuizBuilder = lazy(() => import("./screens/QuizBuilder").then((m) => ({ default: m.QuizBuilder })))
const QuizResults = lazy(() => import("./screens/QuizResults").then((m) => ({ default: m.QuizResults })))
const Announcements = lazy(() =>
  import("./screens/Announcements").then((m) => ({ default: m.Announcements })),
)
const TeacherNotifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.TeacherNotifications })),
)
// Settings is a dialog over the current page (`SettingsModalRoute`), one
// route per tab, each tab's section lazy on its own.
// Each imported from its own module rather than the `@/portals/settings`
// barrel: importing them all through one barrel module means a chunk
// containing any one of them pulls in the code for all of them, defeating the
// per-screen splitting this whole file otherwise does.
const SettingsModalRoute = lazy(() =>
  import("@/portals/settings/SettingsModal").then((m) => ({
    default: m.SettingsModalRoute,
  })),
)
const ProfileSettingsSection = lazy(() =>
  import("@/portals/settings/ProfileSettings").then((m) => ({
    default: m.ProfileSettingsSection,
  })),
)
const AccountSettingsSection = lazy(() =>
  import("@/portals/settings/AccountSettings").then((m) => ({ default: m.AccountSettingsSection })),
)
const NotificationSettingsSection = lazy(() =>
  import("@/portals/settings/NotificationSettings").then((m) => ({
    default: m.NotificationSettingsSection,
  })),
)
const AppearanceSettingsSection = lazy(() =>
  import("@/portals/settings/AppearanceSettings").then((m) => ({
    default: m.AppearanceSettingsSection,
  })),
)
const ClassesSettingsSection = lazy(() =>
  import("@/portals/settings/ClassesSettings").then((m) => ({
    default: m.ClassesSettingsSection,
  })),
)
const InstallSettingsSection = lazy(() =>
  import("@/portals/settings/InstallSettings").then((m) => ({
    default: m.InstallSettingsSection,
  })),
)

// T-15..T-18 and T-21 (tutoring marketplace): the teacher's own tutoring screens.
const TutoringHome = lazy(() =>
  import("./screens/tutoring/TutoringHome").then((m) => ({ default: m.TutoringHome })),
)
const TutorProfileEditor = lazy(() =>
  import("./screens/tutoring/TutorProfileEditor").then((m) => ({ default: m.TutorProfileEditor })),
)
const Availability = lazy(() =>
  import("./screens/tutoring/Availability").then((m) => ({ default: m.Availability })),
)
const TutorSessionDetail = lazy(() =>
  import("./screens/tutoring/TutorSessionDetail").then((m) => ({ default: m.TutorSessionDetail })),
)
const PreviewReviews = lazy(() =>
  import("./screens/tutoring/PreviewReviews").then((m) => ({ default: m.PreviewReviews })),
)
// T-19 and T-20: the students who share their progress with this tutor.
const MyStudents = lazy(() =>
  import("./screens/tutoring/MyStudents").then((m) => ({ default: m.MyStudents })),
)
const TutorStudentDetail = lazy(() =>
  import("./screens/tutoring/TutorStudentDetail").then((m) => ({ default: m.TutorStudentDetail })),
)

/** The teacher bell panel's portal facts. */
export const TEACHER_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: (notification) => staffDestinationFor("teacher", notification),
  iconFor: (type) => {
    if (type === "announcement") return <ShellIcon name="mega" />
    if (type === "at_risk_alert") return <Warning size={18} aria-hidden="true" />
    return <ShellIcon name="bell" />
  },
  inboxTo: INBOX_TO,
  footerLinks: [
    { to: INBOX_TO, label: "All notifications" },
    { to: ANNOUNCEMENTS_TO, label: "Announcements" },
  ],
  emptyMessage: `${TEACHER_INBOX_EMPTY.heading}. ${TEACHER_INBOX_EMPTY.body}`,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

/** The teacher account panel's links, in order. */
export const TEACHER_ACCOUNT_LINKS: readonly AccountLink[] = [
  { id: "profile", label: "Edit profile", to: PROFILE_EDIT_TO, overlay: true, icon: <ShellIcon name="user" /> },
  { id: "settings", label: "Settings", to: SETTINGS_TO, overlay: true, icon: <Gear size={18} aria-hidden="true" /> },
  {
    id: "help",
    label: "Help and feedback",
    description: "Email the Lemely team",
    href: HELP_HREF,
    icon: <Lifebuoy size={18} aria-hidden="true" />,
  },
]

const SIDEBAR_PRIMARY: NavItem["icon"][] = ["overview", "grading", "review", "classes", "atRisk"]
const SIDEBAR_TOOLS: NavItem["icon"][] = ["schemes", "quizzes", "tutoring", "announcements", "deleted"]

const NAV_ICON: Record<NavItem["icon"], ReactNode> = {
  overview: <ShellIcon name="home" />,
  grading: <FileText size={18} aria-hidden="true" />,
  // The review queue holds the marks the system was not confident enough to
  // apply on its own, so the glyph is a seal with a question in it rather than
  // a checklist: what is waiting here is doubt, not tasks.
  review: <SealQuestion size={18} aria-hidden="true" />,
  classes: <ShellIcon name="class" />,
  atRisk: <Warning size={18} aria-hidden="true" />,
  schemes: <Books size={18} aria-hidden="true" />,
  quizzes: <Sparkle size={18} aria-hidden="true" />,
  tutoring: <GraduationCap size={18} aria-hidden="true" />,
  announcements: <ShellIcon name="mega" />,
  notifications: <ShellIcon name="bell" />,
  settings: <Gear size={18} aria-hidden="true" />,
  deleted: <ShellIcon name="trash" />,
}

/*
 * Rows render through the shared shell's `ShellNavList` (`useTeacherSidebar`
 * below). The review-queue count is resolved there (not inside
 * `NavShellItem.badge`, which is a plain `string | number`) and passed in as
 * that row's badge value.
 */
function toNavShellItem(
  item: NavItem,
  options: { forceActive?: boolean; badge?: string | number; urgent?: boolean } = {},
): NavShellItem {
  return {
    id: item.to,
    to: item.to,
    end: item.end,
    label: item.label,
    icon: NAV_ICON[item.icon],
    active: options.forceActive,
    badge: options.badge,
    urgent: options.urgent,
  }
}

/**
 * Sidebar "Your classes" list (the shell renders the group label). Wired to `GET /teacher/classes`
 * (`useTeacherClasses()`) — replaces the mock's 3 hardcoded classes
 * (`recentClasses` in `./data.ts`, one of them fake-flagged "active" with no
 * real "current class" concept anywhere in the app to back it). Capped at 5
 * with a link to the full list rather than an unbounded sidebar.
 */
export function ClassesNavList({ labelledBy }: { labelledBy: string }) {
  const { data, isPending, isError } = useTeacherClasses()

  return (
    <div role="group" aria-labelledby={labelledBy} className="flex flex-col gap-px">
      {isPending ? (
        <div className="px-2.5 py-[7px] text-body-sm text-on-surface-variant">Loading…</div>
      ) : isError ? (
        <div className="px-2.5 py-[7px] text-body-sm text-on-surface-variant">Couldn't load classes.</div>
      ) : data.classes.length === 0 ? (
        <Link
          to="/teacher/classes"
          className="px-2.5 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-on-primary-container hover:underline rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          Add your first class <ForwardArrow />
        </Link>
      ) : (
        <>
          {data.classes.slice(0, 5).map((c) => (
            // A `NavLink`, not a plain `Link`: this row is a navigation
            // destination like any other in the sidebar, so it tells a
            // teacher which class they are looking at. No `end` — the
            // default (non-exact) match is deliberate, since this row must
            // also read as current on the class's `/analytics` child.
            //
            // The grade chip is the server's median latest paper grade
            // (`ClassSummary.grade`), shown only when it exists. The
            // trailing figure is the real `studentCount`.
            <NavLink
              key={c.id}
              to={`/teacher/classes/${c.id}`}
              // §6.1's 44px floor on coarse pointers.
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-chip px-2.5 py-1.5 pointer-coarse:min-h-11 text-label transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                  isActive
                    ? "bg-primary-container text-primary"
                    : "text-on-surface hover:bg-surface-container",
                )
              }
            >
              <span className="truncate">{c.label}</span>
              {c.grade ? (
                <span className={cn("ms-auto inline-flex h-4.5 min-w-6 flex-none items-center justify-center rounded-md px-1 pt-0.5 text-data-sm font-bold", gradeChipClass(c.grade, { size: "small" }))}>
                  <span className="sr-only">Median grade </span>
                  {c.grade}
                </span>
              ) : null}
              <span className={cn("inline-flex h-4.5 w-6 flex-none items-center justify-end pt-0.5 text-data-sm tabular-nums text-on-surface-variant", !c.grade && "ms-auto")}>
                {c.studentCount}
              </span>
            </NavLink>
          ))}
          {data.classes.length > 5 ? (
            <Link
              to="/teacher/classes"
              className="px-2.5 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-on-surface-variant transition-colors hover:text-on-surface rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              See all {data.classes.length} <ForwardArrow />
            </Link>
          ) : null}
        </>
      )}
    </div>
  )
}

/**
 * The teacher sidebar's content; the shell renders it as the rail and the
 * drawer. The identity block's name falls back to the email's local part and
 * its detail is the caller's real platform role, never a fabricated
 * department. No at-risk badge: summing per-class `atRiskCount` double-counts
 * a student in several classes, and the layout has no deduplicated student
 * count. A missing number beats a wrong one. Notifications and Settings live
 * in the top bar, so the sidebar carries the work sections and the tools.
 */
function useTeacherSidebar(): ShellSidebarContent {
  const location = useLocation()
  // Same query `ClassesNavList` subscribes to: react-query dedupes by queryKey.
  const { data } = useTeacherClasses()
  const visibleClassIds = data?.classes.slice(0, 5).map((c) => c.id) ?? []
  // `BottomNav`'s Review tab subscribes to the same hook, so the two badges
  // share one deduped `limit: 1` request.
  const reviewQueueCount = useReviewQueueCount()
  const reviewBadge = reviewQueueCount && reviewQueueCount > 0 ? reviewQueueCount : undefined
  const profile = useProfile()
  const toShell = (item: NavItem) =>
    toNavShellItem(item, {
      forceActive: item.to === "/teacher/classes" ? classesItemActive(location.pathname, visibleClassIds) : undefined,
      badge: item.badge === "review-queue" ? reviewBadge : undefined,
      urgent: item.badge === "review-queue",
    })
  return {
    navLabel: "Teacher",
    homeTo: "/teacher",
    homeLabel: "Lemely, overview",
    items: navItems.filter((i) => SIDEBAR_PRIMARY.includes(i.icon)).map(toShell),
    groups: [
      { id: "classes", label: "Your classes", render: (labelId) => <ClassesNavList labelledBy={labelId} /> },
      {
        id: "tools",
        label: "Tools",
        render: (labelId) => (
          <ShellNavList aria-labelledby={labelId} items={navItems.filter((i) => SIDEBAR_TOOLS.includes(i.icon)).map(toShell)} />
        ),
      },
    ],
    footerAction: (
      <Link to="/teacher/grading" className={SHELL_BUTTON_PRIMARY}>
        <ShellIcon name="up" />
        Upload papers
      </Link>
    ),
    user: profile.data ? (
      <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={roleLabel(profile.data.role)} />
    ) : (
      <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
    ),
  }
}

// One boundary around the Outlet (not per-route): sidebar and chrome stay
// mounted and interactive while a screen chunk loads. Fallback is the shared
// `RouteFallback` (C-11 state-view family); see the student portal for the
// reasoning, and `state-views.tsx` for why it is not a full `StateView`.

/** The teacher's own bar buttons: Create (tonal) and Upload papers (primary). */
function TeacherTopBarActions() {
  return (
    <>
      <CreateSheet
        triggerClassName={cn(
          SHELL_BUTTON_TONAL,
          "max-sm:w-9 max-sm:justify-center max-sm:px-0 max-sm:pointer-coarse:w-11",
        )}
      />
      <Link to="/teacher/grading" className={cn(SHELL_BUTTON_PRIMARY, "me-2.5 max-shell-sm:hidden")}>
        <ShellIcon name="up" />
        Upload papers
      </Link>
    </>
  )
}

/** The four route-backed BottomNav tabs, exported so `navigation.test.ts` can
 * assert each `to` resolves to a mounted route without rendering the shell.
 * Labels declared in tab order ("Overview", "Grading", "Review", "Classes")
 * ahead of `TeacherLayout`'s own "More" so `navShells.test.ts`'s ordered
 * regex over the stripped source sees all five labels in the same order the
 * bar renders them. */
export const TEACHER_BOTTOM_TABS: readonly {
  id: string
  label: string
  to: string
  end?: boolean
  icon: Icon
}[] = [
  { id: "overview", label: "Overview", to: "/teacher", end: true, icon: SquaresFour },
  { id: "grading", label: "Grading", to: "/teacher/grading", icon: FileText },
  { id: "review", label: "Review", to: "/teacher/review", icon: SealQuestion },
  { id: "classes", label: "Classes", to: "/teacher/classes", icon: ChartBar },
]

function TeacherLayout() {
  const location = useLocation()
  // Same query the class list subscribes to (deduped by key); a pending list
  // shows the skeleton inside the shell. A zero-class teacher sees setup on home.
  const classesQuery = useTeacherClasses()
  // Shares its request with the sidebar's own subscriber (same query key).
  const reviewQueueCount = useReviewQueueCount()
  const { data: profile } = useProfile()
  const sidebar = useTeacherSidebar()
  // While Settings is a dialog the page underneath is still the page: title
  // and trail follow the background location. The trail renders at every
  // width (the D1.5 back affordance for drilled-into screens).
  const trail = resolveTrail(
    underlyingPathname({ pathname: location.pathname, state: location.state, overlayBase: TEACHER_SETTINGS_BASE }),
  )
  return (
    <PortalShell
      portal="teacher"
      drawerTitle="Lemely"
      pending={classesQuery.isPending}
      overlay={{ routes: teacherContentRoutes(), overlayBase: TEACHER_SETTINGS_BASE, fallbackPath: "/teacher" }}
      sidebar={sidebar}
      topBar={{
        title: trail[trail.length - 1]?.label ?? "Overview",
        trail,
        navLabel: "Open teacher navigation",
        actions: <TeacherTopBarActions />,
        notifications: TEACHER_NOTIFICATIONS_PANEL,
        settingsTo: TEACHER_SETTINGS_BASE,
        account: { links: TEACHER_ACCOUNT_LINKS, detail: profile ? roleLabel(profile.role) : null },
      }}
      bottomTabs={TEACHER_BOTTOM_TABS.map(
        (tab): NavShellItem => ({
          id: tab.id,
          to: tab.to,
          end: tab.end,
          label: tab.label,
          icon: <tab.icon size={22} aria-hidden="true" />,
          badge: tab.id === "review" && reviewQueueCount && reviewQueueCount > 0 ? reviewQueueCount : undefined,
        }),
      )}
    />
  )
}

export const teacherRoute: RouteObject = {
  path: "teacher",
  element: <TeacherLayout />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    {
      index: true,
      element: <Overview />,
      handle: { title: "Teacher dashboard", skeleton: "card-grid" },
    },
    {
      path: "grading",
      element: <Grading />,
      handle: { title: "Grading console", skeleton: "page-header" },
    },
    {
      path: "deleted",
      element: <RecentlyDeleted />,
      handle: { title: "Recently deleted", skeleton: "list" },
    },
    {
      path: "review",
      element: <Review />,
      handle: { title: "Review queue", skeleton: "list" },
    },
    {
      path: "review/:itemId",
      element: <ReviewItem />,
      handle: { title: "Review a mark", skeleton: "page-header" },
    },
    {
      path: "classes",
      element: <Classes />,
      handle: { title: "Classes", skeleton: "card-grid" },
    },
    {
      path: "classes/:classId",
      element: <ClassDetailLayout />,
      // The layout carries a title so its `index` child (the roster) inherits
      // one, and `analytics` overrides it. Deepest wins, so this is the
      // fallback rather than a competing entry.
      handle: { title: "Class", skeleton: "page-header" },
      children: [
        {
          index: true,
          element: <ClassRoster />,
          handle: { title: "Class roster", skeleton: "page-header" },
        },
        {
          path: "analytics",
          element: <ClassAnalytics />,
          handle: { title: "Class analytics", skeleton: "page-header" },
        },
        {
          path: "papers",
          element: <ClassPapers />,
          handle: { title: "Class papers", skeleton: "page-header" },
        },
      ],
    },
    // D7.10 / Task 21. Deliberately not in `navItems` (`./data.ts`), matching
    // `/student/onboard`'s exclusion from the student nav for the identical
    // reason: this is a gate destination, not a standing section a teacher
    // with classes already has any reason to navigate to. It stays mounted
    // and deep-linkable regardless — the setup screen only
    // ever sends a teacher here, it does not gate this route itself, so a
    // teacher who already has classes can still open it directly (e.g. to
    // create a second class the same way) without being bounced.
    {
      path: "first-class",
      element: <CreateFirstClass />,
      handle: { title: "Create a class", skeleton: "page-header" },
    },
    {
      path: "students/:studentId",
      element: <StudentDetail />,
      handle: { title: "Student", skeleton: "page-header" },
    },
    {
      path: "at-risk",
      element: <AtRiskList />,
      handle: { title: "Students at risk", skeleton: "list" },
    },
    {
      path: "schemes",
      element: <MarkSchemes />,
      handle: { title: "Mark schemes", skeleton: "list" },
    },
    {
      path: "quizzes",
      element: <Quizzes />,
      handle: { title: "Quizzes", skeleton: "card-grid" },
    },
    {
      path: "quizzes/:quizId",
      element: <QuizBuilder />,
      handle: { title: "Quiz builder", skeleton: "page-header" },
    },
    // T-10 is per assignment, never per quiz (§1.6) — the route shape is the
    // first place that has to say so.
    {
      path: "quizzes/:quizId/assignments/:assignmentId/results",
      element: <QuizResults />,
      handle: { title: "Quiz results", skeleton: "page-header" },
    },
    {
      path: "tutoring",
      element: <TutoringHome />,
      handle: { title: "Tutoring", skeleton: "list" },
    },
    {
      path: "tutoring/profile",
      element: <TutorProfileEditor />,
      handle: { title: "Tutor profile", skeleton: "page-header" },
    },
    {
      path: "tutoring/availability",
      element: <Availability />,
      handle: { title: "Weekly availability", skeleton: "page-header" },
    },
    {
      path: "tutoring/sessions/:bookingId",
      element: <TutorSessionDetail />,
      handle: { title: "Tutoring session", skeleton: "page-header" },
    },
    {
      path: "tutoring/preview",
      element: <PreviewReviews />,
      handle: { title: "Profile preview and reviews", skeleton: "page-header" },
    },
    {
      path: "tutoring/students",
      element: <MyStudents />,
      handle: { title: "My students", skeleton: "list" },
    },
    {
      path: "tutoring/students/:studentId",
      element: <TutorStudentDetail />,
      handle: { title: "Student progress", skeleton: "page-header" },
    },
    {
      path: "announcements",
      element: <Announcements />,
      handle: { title: "Announcements", skeleton: "list" },
    },
    {
      path: "notifications",
      element: <TeacherNotifications />,
      handle: { title: "Notifications", skeleton: "list" },
    },
    {
      // A dialog over the current page: `ScreenOutlet`'s overlay (in the layout)
      // renders the page underneath, this route renders the dialog. One child
      // per entry in `TEACHER_SETTINGS_TABS`; `settingsTabs.test.ts` holds the
      // two in step. Paths are unchanged from the page-based settings.
      path: "settings",
      element: (
        <SettingsModalRoute
          tabs={TEACHER_SETTINGS_TABS}
          basePath={TEACHER_SETTINGS_BASE}
          fallbackPath="/teacher"
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
          // R10: the only portal that shows `reviewWithdrawn` — it fires
          // only for a teacher (Task 9's `_notify_withdrawn_reviewers`).
          element: <NotificationSettingsSection showTeacherOnly />,
          handle: { title: "Notification settings", skeleton: "page-header" },
        },
        {
          path: "appearance",
          element: <AppearanceSettingsSection />,
          handle: { title: "Appearance", skeleton: "page-header" },
        },
        {
          path: "classes",
          element: <ClassesSettingsSection />,
          handle: { title: "Classes and grading", skeleton: "page-header" },
        },
        {
          path: "install",
          element: <InstallSettingsSection />,
          handle: { title: "Install Lemely", skeleton: "page-header" },
        },
      ],
    },
    // P4.10. Last, so it only matches what nothing above did — an unmatched
    // path in this portal used to fall to the top-level `*` and cost the
    // reader the sidebar. See `portals/misc/NotFound.tsx`.
    {
      path: "*",
      element: <PortalNotFound />,
      handle: { title: "Page not found", skeleton: "page-header" },
    },
  ],
}

let contentRoutesCache: RouteObject[] | null = null

/** The portal's child routes minus the settings dialog, matched against the
 * page underneath while the dialog is open (`ScreenOutlet`'s `overlay`, in
 * `TeacherLayout`; everywhere else it is the plain screen outlet). Built once, on first use, because
 * `teacherRoute` is declared after the layout that reads it. */
function teacherContentRoutes(): RouteObject[] {
  contentRoutesCache ??= (teacherRoute.children ?? []).filter((route) => route.path !== "settings")
  return contentRoutesCache
}
