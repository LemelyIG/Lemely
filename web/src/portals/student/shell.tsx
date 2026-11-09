import { Link, matchPath, useLocation } from "react-router-dom"
import { ChalkboardTeacher, House, NotePencil, UserCircle, type Icon } from "@phosphor-icons/react"
import type { AccountLink } from "@/components/shell/AccountPanel"
import { ShellIcon, type ShellIconName } from "@/components/shell/icons"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"
import { PortalShell } from "@/components/shell/PortalShell"
import { profileName } from "@/components/shell/ShellAvatar"
import { ShellUserBlock } from "@/components/shell/ShellSidebar"
import { ShellTree, type ShellTreeRow } from "@/components/shell/ShellTree"
import { SHELL_BUTTON_PRIMARY } from "@/components/shell/shellStyles"
import { BackControl } from "@/components/ui/back-control"
import type { NavShellItem } from "@/components/ui/nav-shells"
import type { ScreenOverlay } from "@/components/ui/screen-outlet"
import { useProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { underlyingPathname } from "@/lib/nav/backgroundLocation"
import type { prefetchOnIntent } from "@/lib/prefetchOnIntent"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
import { STAFF_INBOX_ERROR } from "@/lib/staffInbox"
import { studentDestinationFor } from "@/lib/studentInbox"
import type { SubjectRow } from "@/lib/studentTypes"
import { cn } from "@/lib/utils"
import { GradeRing } from "./GradeRing"
import {
  STUDENT_INBOX_EMPTY,
  currentSubjectCode,
  studentAccountLinks,
  studentDetailLine,
  studentInboxLinks,
  studentNavItems,
  studentPageTitle,
  studentShellTrail,
  type NavItem,
} from "./data"

export const STUDENT_SETTINGS_BASE = "/student/settings"

/** The four route-backed phone tabs, unchanged from `develop` (approved
 * drift). Declared in tab order; the shell appends "More". */
export const STUDENT_BOTTOM_TABS: readonly { id: string; label: string; to: string; end?: boolean; icon: Icon }[] = [
  { id: "overview", label: "Overview", to: "/student", end: true, icon: House },
  { id: "correct", label: "Correct", to: "/student/correct", icon: NotePencil },
  { id: "classes", label: "Classes", to: "/student/classes", icon: ChalkboardTeacher },
  { id: "profile", label: "Profile", to: "/student/profile", icon: UserCircle },
]

function NavGlyph({ icon }: { icon: NavItem["icon"] }) {
  if (typeof icon === "string") return <ShellIcon name={icon} />
  const Glyph = icon
  return <Glyph size={18} aria-hidden="true" />
}

const toShellItem = (item: NavItem): NavShellItem => ({
  id: item.to,
  to: item.to,
  end: item.end,
  label: item.label,
  icon: <NavGlyph icon={item.icon} />,
})

const TYPE_ICON: Record<string, ShellIconName> = {
  announcement: "mega",
  grade_ready: "review",
  study_plan_reminder: "plan",
  // `streak_warning` keeps the bell: design A's shell set has no flame or
  // streak glyph, and borrowing "trophy" would read as an achievement.
}

const STUDENT_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: studentDestinationFor,
  iconFor: (type) => <ShellIcon name={TYPE_ICON[type] ?? "bell"} />,
  inboxTo: "/student/notifications",
  footerLinks: studentInboxLinks.map(({ to, label }) => ({ to, label })),
  emptyMessage: STUDENT_INBOX_EMPTY,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

const STUDENT_ACCOUNT_LINKS: readonly AccountLink[] = studentAccountLinks.map((link) => ({
  id: link.to,
  label: link.label,
  to: link.to,
  icon: <NavGlyph icon={link.icon} />,
}))

function subjectRows(subjects: readonly SubjectRow[]): ShellTreeRow[] {
  return subjects.map((s) => ({
    id: s.code,
    label: s.name,
    title: `${s.name} · ${s.code}`,
    // No trailing code: design A hides `.as-code` in the sidebar (`.as-side .as-subj .as-code`).
    adornment: s.grade ? <GradeRing grade={s.grade} pct={s.pct} /> : null,
    children: [
      { id: `${s.code}-practice`, label: "Practice", to: `/student/practice/${s.code}`, icon: <ShellIcon name="practice" /> },
      { id: `${s.code}-cards`, label: "Flashcards", to: `/student/flashcards/${s.code}`, icon: <ShellIcon name="cards" /> },
      { id: `${s.code}-plan`, label: "Study plan", to: `/student/plan/${s.code}`, icon: <ShellIcon name="plan" /> },
    ],
  }))
}

export interface StudentShellProps {
  pending: boolean
  prefetchCorrectPaper: ReturnType<typeof prefetchOnIntent>
  overlay?: ScreenOverlay
}

/** The student portal's content for the shared shell (portal shell spec §1). */
export function StudentShell({ pending, prefetchCorrectPaper, overlay }: StudentShellProps) {
  const location = useLocation()
  // Same queries Overview and Profile read; react-query dedupes by key.
  const overview = useOverview()
  const profile = useProfile()
  const studentProfile = useStudentProfile()
  const { data: reference } = useReference()
  const subjects = overview.data?.subjects ?? []
  // While Settings is a dialog, the title, the current sidebar row and the open
  // subject follow the page underneath (the portal home on a deep link).
  const pagePath = underlyingPathname({
    pathname: location.pathname,
    state: location.state,
    overlayBase: STUDENT_SETTINGS_BASE,
    fallbackPath: "/student",
  })
  const navItems = studentNavItems.map((item) => {
    const shellItem = toShellItem(item)
    // The row's own NavLink matches the URL, which is the dialog's while it is open.
    return pagePath !== location.pathname && matchPath({ path: item.to, end: item.end }, pagePath)
      ? { ...shellItem, active: true }
      : shellItem
  })
  const trail = studentShellTrail(pagePath)
  const detail = studentDetailLine(
    qualificationLevelLabel(reference?.qualificationLevels, studentProfile.data?.profile.qualificationLevel),
    subjects.length,
  )
  const upload = (className?: string) => (
    <Link to="/student/correct" viewTransition className={cn(SHELL_BUTTON_PRIMARY, className)} {...prefetchCorrectPaper}>
      <ShellIcon name="up" />
      <span>Upload a paper</span>
    </Link>
  )

  return (
    <PortalShell
      portal="student"
      drawerTitle="Lemely"
      pending={pending}
      overlay={overlay}
      sidebar={{
        navLabel: "Main",
        homeTo: "/student",
        homeLabel: "Lemely, overview",
        items: navItems,
        groups: [
          {
            id: "subjects",
            label: "Subjects",
            render: (labelId) => (
              <ShellTree
                labelledBy={labelId}
                rows={subjectRows(subjects)}
                currentId={currentSubjectCode(pagePath)}
                empty={overview.isPending ? null : "Your subjects show up here after your first marked paper."}
              />
            ),
          },
        ],
        footerAction: upload(),
        user: profile.data ? (
          <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={detail} />
        ) : (
          <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
        ),
      }}
      topBar={{
        title: studentPageTitle(pagePath, subjects),
        trail,
        backFallback: "/student",
        navLabel: "Open student navigation",
        actions: (
          <>
            {/* Packet B2a: a drilled-in page's trail has no linked crumb
                ("Practice / 0580"), so below the sidebar column this is the
                way back. Never on a section page, which design A shows bare. */}
            {trail.length > 1 ? <BackControl fallback="/student" className="shell-lg:hidden native:hidden" /> : null}
            {/* Not on the upload screen itself, where it would do nothing. */}
            {location.pathname === "/student/correct" ? null : upload("me-2.5 max-shell-sm:hidden")}
          </>
        ),
        notifications: STUDENT_NOTIFICATIONS_PANEL,
        settingsTo: STUDENT_SETTINGS_BASE,
        account: { links: STUDENT_ACCOUNT_LINKS, detail },
      }}
      bottomTabs={STUDENT_BOTTOM_TABS.map(
        (tab): NavShellItem => ({
          id: tab.id,
          to: tab.to,
          end: tab.end,
          label: tab.label,
          icon: <tab.icon size={22} aria-hidden="true" />,
          prefetch: tab.id === "correct" ? prefetchCorrectPaper.onPointerEnter : undefined,
        }),
      )}
      bottomEmphasisId="correct"
    />
  )
}
