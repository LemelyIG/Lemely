/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useState } from "react"
import { useLocation, useParams } from "react-router-dom"
import { ChatCircleText, EnvelopeSimple, Gear, GraduationCap, House, TextAlignLeft, User, Users, Warning } from "@phosphor-icons/react"
import type { AccountLink } from "@/components/shell/AccountPanel"
import { ShellIcon } from "@/components/shell/icons"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"
import { PortalShell } from "@/components/shell/PortalShell"
import { isTabRoot, titleLevelFor } from "@/components/shell/largeTitle"
import { profileName } from "@/components/shell/ShellAvatar"
import { ShellUserBlock } from "@/components/shell/ShellSidebar"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { useCachedChildSubject, useChildren } from "@/lib/hooks/useParentApi"
import { PARENT_INBOX_EMPTY, STAFF_INBOX_ERROR, staffDestinationFor, unreadBadgeLabel } from "@/lib/staffInbox"
import { ChildSwitcher } from "./ChildSwitcher"
import { type ParentTabId, parentPageTitle, parentShellTrail, parentTabs, resolveChildId, topicsActive, validChildParam } from "./shellModel"

const SETTINGS_TO = "/settings/devices"
const INBOX_TO = "/parent/notifications"

const TAB_ICON: Record<ParentTabId, typeof House> = {
  overview: House,
  topics: TextAlignLeft,
  inbox: ChatCircleText,
  tutoring: User,
}

const PARENT_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: (notification) => staffDestinationFor("parent", notification),
  iconFor: (type) => (type === "at_risk_alert" ? <Warning size={18} aria-hidden="true" /> : <ShellIcon name="bell" />),
  inboxTo: INBOX_TO,
  footerLinks: [{ to: INBOX_TO, label: "All notifications" }],
  emptyMessage: `${PARENT_INBOX_EMPTY.heading}. ${PARENT_INBOX_EMPTY.body}`,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

const PARENT_ACCOUNT_LINKS: readonly AccountLink[] = [
  // The Emails settings screen (mock pa.js FM): weekly summaries per subject and right-away alerts. L11 mounts /parent/emails.
  { id: "emails", label: "Emails", to: "/parent/emails", icon: <EnvelopeSimple size={18} aria-hidden="true" /> },
  { id: "settings", label: "Settings", to: SETTINGS_TO, icon: <Gear size={18} aria-hidden="true" /> },
]

/**
 * The parent portal in the shared shell (F1; approved parent mock SB, pa.js):
 * a child switcher and four tabs (Overview, Topics, Inbox, Tutoring), the
 * switcher in the rail on desktop and in the top bar below it. No Binny.
 * The shell appends More, which holds Tutors and, with 2+ children, Your children.
 */
export function ParentShell() {
  const location = useLocation()
  const { childId: paramChild, code } = useParams<{ childId?: string; code?: string }>()
  const { data, isPending: childrenPending } = useChildren()
  const profile = useProfile()
  const unread = unreadBadgeLabel(useNotificationCounts().data)
  const children = data?.children ?? []
  const childIds = children.map((c) => c.childId)
  // An unknown childId (not one of this parent's children) never reaches the tabs or links: they follow the
  // last or first linked child, the switcher renders nothing, and the page shows its own not-found state.
  const knownChild = validChildParam(paramChild ?? null, childIds, childrenPending)
  const [lastChild, setLastChild] = useState<string | null>(null)
  useEffect(() => {
    if (knownChild) setLastChild(knownChild)
  }, [knownChild])
  const childId = resolveChildId(knownChild, childIds, lastChild)
  const subject = useCachedChildSubject(paramChild ?? "", code ?? "")
  const subjectLabel = subject?.subjectName ?? code ?? null
  const path = location.pathname
  const tabs = parentTabs(childId)
  const trail = parentShellTrail(path, { childId: knownChild, hasChildList: children.length > 1, subjectLabel })
  const titleLevel = titleLevelFor(trail, isTabRoot(path, tabs.map((t) => t.to)))

  const tabItems: NavShellItem[] = tabs.map((tab) => {
    const Glyph = TAB_ICON[tab.id]
    return {
      id: tab.id,
      to: tab.to,
      end: tab.end,
      label: tab.label,
      icon: <Glyph size={22} aria-hidden="true" />,
      activeIcon: <Glyph size={22} weight="fill" aria-hidden="true" />,
      badge: tab.id === "inbox" && unread ? unread : undefined,
      active: tab.id === "topics" && topicsActive(path) ? true : undefined,
    }
  })
  const sidebarItems: NavShellItem[] = [
    ...tabItems.map((item) => ({ ...item, icon: item.icon, activeIcon: undefined })),
    { id: "tutors", to: "/parent/tutors", label: "Tutors", icon: <GraduationCap size={18} aria-hidden="true" /> },
    ...(children.length > 1
      ? [{ id: "children", to: "/parent", end: true, label: "Your children", icon: <Users size={18} aria-hidden="true" /> }]
      : []),
  ]

  return (
    <PortalShell
      portal="parent"
      drawerTitle="Lemely"
      pending={false}
      sidebar={{
        navLabel: "Main",
        homeTo: "/parent",
        homeLabel: "Lemely, your children",
        items: sidebarItems,
        lead: <ChildSwitcher />,
        user: profile.data ? (
          <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={null} />
        ) : (
          <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
        ),
      }}
      topBar={{
        title: parentPageTitle(path, subjectLabel),
        trail,
        titleLevel,
        backFallback: childId ? tabs[0].to : "/parent",
        navLabel: "Open parent navigation",
        actions: <ChildSwitcher className="shell-lg:hidden" />,
        notifications: PARENT_NOTIFICATIONS_PANEL,
        settingsTo: SETTINGS_TO,
        account: { links: PARENT_ACCOUNT_LINKS, detail: null },
      }}
      bottomTabs={tabItems}
    />
  )
}
