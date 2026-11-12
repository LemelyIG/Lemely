import { useState, type ReactNode } from "react"
import { ClipboardText, GraduationCap, House, Users } from "@phosphor-icons/react"
import { ComponentSection, Group, StateCell, FAILURE, FIXTURE_AT_RISK, FIXTURE_CLASSES, FIXTURE_COUNTS, FIXTURE_NOTIFICATIONS, FIXTURE_OVERVIEW, FIXTURE_PROFILE, KEYS, Seeded, type QuerySeed } from "./harness"
import { Button } from "@/components/ui/button"
import { GradeBadge } from "@/components/ui/grade-badge"
import { SidebarNav, type NavShellItem } from "@/components/ui/nav-shells"
import { EmptyState, ErrorState, OfflineState } from "@/components/ui/state-views"
import { gradeChipClass } from "@/lib/grade"
import { cn } from "@/lib/utils"
import { unreadBadgeLabel } from "@/lib/staffInbox"
import { ClassesNavSection, TOP_BAR_ICON_BUTTON } from "@/portals/teacher"
import { NotificationsMenu } from "@/portals/teacher/components/NotificationsMenu"
import { ProfileMenu } from "@/portals/teacher/components/ProfileMenu"
import { CreateSheet } from "@/portals/teacher/components/TopBarSheets"
import { AtRiskTable } from "@/portals/teacher/home/AtRiskTable"
import { ClassStrip } from "@/portals/teacher/home/ClassStrip"
import { MarkClassSet } from "@/portals/teacher/home/MarkClassSet"
import { ReviewQueueTile } from "@/portals/teacher/home/ReviewQueueTile"
import { TeacherHome } from "@/portals/teacher/home/TeacherHome"
import { TeacherSetup } from "@/portals/teacher/home/TeacherSetup"
import { growthModel } from "@/portals/teacher/home/growth"
import { deriveSetup } from "@/portals/teacher/home/setup"
import { SettingsModal } from "@/portals/settings/SettingsModal"
import { TEACHER_SETTINGS_TABS } from "@/portals/settings/settingsTabs"

/*
 * The teacher portal's top bar, sidebar, home and settings shell.
 *
 * Every component here is imported from `src/`; nothing is redrawn. The ones
 * that call react-query hooks sit inside `Seeded`, a per-cell QueryClient
 * pre-filled from the fixtures in harness.tsx, so the page makes no API call.
 * `interact` cells are real Radix or router behaviour that needs a click.
 */

const noop = () => {}

const SEED_PROFILE: QuerySeed = { data: [[KEYS.profile, FIXTURE_PROFILE]] }
const SEED_INBOX: QuerySeed = {
  data: [
    [KEYS.inbox, FIXTURE_NOTIFICATIONS],
    [KEYS.counts, FIXTURE_COUNTS],
  ],
}
const SEED_INBOX_EMPTY: QuerySeed = {
  data: [
    [KEYS.inbox, { notifications: [] }],
    [KEYS.counts, { unread: 0, total: 0, unreadByType: {} }],
  ],
}
const SEED_INBOX_ERROR: QuerySeed = { errors: [[KEYS.inbox, FAILURE]] }
const SEED_CLASSES: QuerySeed = { data: [[KEYS.classes, { classes: FIXTURE_CLASSES }]] }
const SEED_CLASSES_MANY: QuerySeed = {
  data: [[KEYS.classes, { classes: [...FIXTURE_CLASSES, ...FIXTURE_CLASSES.map((c) => ({ ...c, id: `${c.id}b`, label: `${c.label} B` }))] }]],
}
const SEED_CLASSES_NONE: QuerySeed = { data: [[KEYS.classes, { classes: [] }]] }
const SEED_CLASSES_ERROR: QuerySeed = { errors: [[KEYS.classes, FAILURE]] }

const HOME_SEEDS: Record<"overview" | "setup" | "error" | "loading", QuerySeed> = {
  overview: { data: [[KEYS.classes, { classes: FIXTURE_CLASSES }], [KEYS.overview, FIXTURE_OVERVIEW]] },
  setup: {
    data: [
      [KEYS.classes, { classes: [FIXTURE_CLASSES[0]!] }],
      [KEYS.overview, { ...FIXTURE_OVERVIEW, paperCount: 0, pendingReviewCount: 0, atRisk: [] }],
    ],
  },
  error: { errors: [[KEYS.classes, FAILURE], [KEYS.overview, FAILURE]] },
  loading: {},
}

/** A bar of the real top-bar trigger, so a menu is seen in the context it ships in. */
const unlocksFor = (classes: typeof FIXTURE_CLASSES) => growthModel(classes, { paperCount: 0, atRisk: [] }).unlocks

function TopBarCell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-14 w-full items-center justify-end gap-1 rounded-chip border border-outline-variant bg-surface px-3">
      {children}
    </div>
  )
}

function BellCell({ seed, badge }: { seed: QuerySeed; badge: string | null }) {
  return (
    <Seeded seed={seed}>
      <TopBarCell>
        <NotificationsMenu unread={badge} triggerClassName={TOP_BAR_ICON_BUTTON} />
      </TopBarCell>
    </Seeded>
  )
}

const NAV_ITEMS: NavShellItem[] = [
  { id: "overview", label: "Overview", to: "/", end: true, icon: <House size={18} aria-hidden="true" /> },
  { id: "review", label: "Review queue", to: "/teacher/review", badge: 14, urgent: true, icon: <ClipboardText size={18} aria-hidden="true" /> },
  { id: "classes", label: "Classes", to: "/teacher/classes", badge: 4, icon: <Users size={18} aria-hidden="true" /> },
  { id: "schemes", label: "Mark schemes", to: "/teacher/schemes", icon: <GraduationCap size={18} aria-hidden="true" /> },
]

function SidebarFrame({ children }: { children: ReactNode }) {
  return (
    <div className="w-full max-w-[252px] rounded-card bg-surface-container-lowest p-3 dark:bg-surface-container-high">{children}</div>
  )
}

function HomeFrame({ children }: { children: ReactNode }) {
  return <div className="w-full min-w-0 rounded-card border border-outline-variant bg-surface p-2 sm:p-4">{children}</div>
}

function SettingsDemo() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Open settings
      </Button>
      {open ? (
        <SettingsModal
          title="Settings"
          tabs={TEACHER_SETTINGS_TABS}
          basePath="/teacher/settings"
          activeTab={TEACHER_SETTINGS_TABS[0] ?? null}
          onClose={() => setOpen(false)}
        >
          <p className="text-body-md text-on-surface-variant">
            Each tab is a route that renders its own panel here. The preview has no routes, so the panel is this sentence; the frame, tab rail, heading and close behaviour are the real component.
          </p>
        </SettingsModal>
      ) : null}
    </>
  )
}

const GRADES = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"] as const

export function TeacherGroup() {
  return (
    <Group title="Teacher portal">
      <ComponentSection
        name="Top bar"
        summary="Create, notifications and the profile menu, in the real top-bar button style. Each opens a Radix layer, so hover, focus and open are live. Data is seeded per cell; nothing calls an API."
      >
        <StateCell state="default" provenance="live" note="CreateSheet. Click Create to open the sheet of four starting points.">
          <TopBarCell>
            <CreateSheet triggerClassName="inline-flex h-9 items-center gap-2 rounded-button bg-primary px-3.5 btn-text text-on-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" />
          </TopBarCell>
        </StateCell>
        <StateCell state="default" provenance="live" note="ProfileMenu with a seeded profile. Click the avatar.">
          <Seeded seed={SEED_PROFILE}>
            <TopBarCell>
              <ProfileMenu />
            </TopBarCell>
          </Seeded>
        </StateCell>
        <StateCell state="loading" provenance="prop" note="ProfileMenu while the profile is pending: the real hook, never answered.">
          <Seeded seed={{}}>
            <TopBarCell>
              <ProfileMenu />
            </TopBarCell>
          </Seeded>
        </StateCell>
        <StateCell state="default" provenance="live" note="NotificationsMenu, 2 unread. Click the bell: three rows, Mark all read, two footer links.">
          <BellCell seed={SEED_INBOX} badge={unreadBadgeLabel(FIXTURE_COUNTS)} />
        </StateCell>
        <StateCell state="success" provenance="live" note="NotificationsMenu, all read: no badge, no Mark all read. Open it to see the empty copy.">
          <BellCell seed={SEED_INBOX_EMPTY} badge={null} />
        </StateCell>
        <StateCell state="loading" provenance="live" note="NotificationsMenu, inbox pending. Open it to see the Loading line; the request never answers here.">
          <BellCell seed={{}} badge={null} />
        </StateCell>
        <StateCell state="error" provenance="live" note="NotificationsMenu, inbox failed. Open it to see the alert and Try again.">
          <BellCell seed={SEED_INBOX_ERROR} badge={null} />
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Sidebar"
        summary="The nav row with its count badge (filled when urgent), and the Your classes list: a Jewel grade chip, then the student count. No chip appears for a class with no graded paper."
      >
        <StateCell state="default" provenance="prop" note="SidebarNav, variant abyss. Overview is the current row; Review queue is urgent (filled count); Classes is a plain count.">
          <SidebarFrame>
            <SidebarNav variant="abyss" items={NAV_ITEMS} />
          </SidebarFrame>
        </StateCell>
        <StateCell state="default" provenance="prop" note="ClassesNavSection with four seeded classes. The last has no grade, so no chip.">
          <SidebarFrame>
            <Seeded seed={SEED_CLASSES}>
              <ClassesNavSection />
            </Seeded>
          </SidebarFrame>
        </StateCell>
        <StateCell state="default" provenance="prop" note="More than five classes: the list caps at five and links to the rest.">
          <SidebarFrame>
            <Seeded seed={SEED_CLASSES_MANY}>
              <ClassesNavSection />
            </Seeded>
          </SidebarFrame>
        </StateCell>
        <StateCell state="default" provenance="prop" note="No classes yet: a single link to add the first.">
          <SidebarFrame>
            <Seeded seed={SEED_CLASSES_NONE}>
              <ClassesNavSection />
            </Seeded>
          </SidebarFrame>
        </StateCell>
        <StateCell state="loading" provenance="prop" note="Classes pending.">
          <SidebarFrame>
            <Seeded seed={{}}>
              <ClassesNavSection />
            </Seeded>
          </SidebarFrame>
        </StateCell>
        <StateCell state="error" provenance="prop" note="Classes failed to load.">
          <SidebarFrame>
            <Seeded seed={SEED_CLASSES_ERROR}>
              <ClassesNavSection />
            </Seeded>
          </SidebarFrame>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Grade chips"
        summary="gradeChipClass at both sizes for every grade, the way the sidebar, class cards and at-risk rows draw them. Small is outlined; large is a Jewel fill with a white letter."
      >
        <StateCell state="default" provenance="prop" note="small, as in the sidebar class row">
          <div className="flex flex-wrap gap-2">
            {GRADES.map((g) => (
              <span key={g} className={cn("inline-flex h-4.5 min-w-6 items-center justify-center rounded-md px-1 pt-0.5 text-data-sm font-bold", gradeChipClass(g, { size: "small" }))}>
                {g}
              </span>
            ))}
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="large">
          <div className="flex flex-wrap gap-2">
            {GRADES.map((g) => (
              <span key={g} className={cn("inline-flex h-8 min-w-10 items-center justify-center rounded-chip px-2 text-display-xs", gradeChipClass(g, { size: "large" }))}>
                {g}
              </span>
            ))}
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="GradeBadge hero, achieved: the headline grade">
          <div className="flex flex-wrap gap-3">
            {GRADES.map((g) => (
              <GradeBadge key={g} grade={g} size="hero" />
            ))}
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="GradeBadge medium, achieved">
          <div className="flex flex-wrap gap-3">
            {GRADES.map((g) => (
              <GradeBadge key={g} grade={g} size="medium" />
            ))}
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="GradeBadge inline, achieved">
          <div className="flex flex-wrap gap-3">
            {GRADES.map((g) => (
              <GradeBadge key={g} grade={g} size="inline" />
            ))}
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="Provisional bases: predicted, target, and estimated (dashed, always labelled)">
          <div className="flex flex-wrap gap-4">
            <GradeBadge grade="B" size="medium" basis="predicted" />
            <GradeBadge grade="A" size="medium" basis="target" />
            <GradeBadge grade="C" size="medium" basis="achieved" estimated />
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Home: class strip"
        summary="One card per class with its median grade, trend and weakest topic. Each card is a link and lifts on hover. A class with no graded paper shows no chip and no trend rather than a placeholder."
      >
        <StateCell wide state="default" provenance="prop" note="ClassStrip, four seeded classes (A*, B, C and ungraded). It scrolls sideways; drag with a mouse.">
          <div className="w-full min-w-0">
            <ClassStrip classes={FIXTURE_CLASSES} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="prop" note="ClassStrip with no classes renders nothing at all. The empty home is TeacherSetup, below.">
          <div className="w-full min-w-0">
            <ClassStrip classes={[]} />
            <p className="text-body-sm text-on-surface-variant">(nothing rendered above this line)</p>
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Home: review queue and marking"
        summary="The review tile shows the open queue as a confidence histogram against the server threshold; the mark card takes a PDF drop anywhere on the page."
      >
        <StateCell wide state="default" provenance="prop" note="ReviewQueueTile, 14 items, some below the 90% threshold">
          <div className="w-full min-w-0">
            <ReviewQueueTile overview={FIXTURE_OVERVIEW} />
          </div>
        </StateCell>
        <StateCell wide state="success" provenance="prop" note="ReviewQueueTile, queue empty">
          <div className="w-full min-w-0">
            <ReviewQueueTile overview={{ ...FIXTURE_OVERVIEW, pendingReviewCount: 0, reviewConfidenceBuckets: [], reviewEstimateMinutes: 0 }} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="prop" note="ReviewQueueTile, every item low confidence">
          <div className="w-full min-w-0">
            <ReviewQueueTile overview={{ ...FIXTURE_OVERVIEW, pendingReviewCount: 6, reviewConfidenceBuckets: [2, 1, 1, 0, 1, 1, 0, 0, 0, 0], reviewEstimateMinutes: 2 }} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="live" note="MarkClassSet, nothing marked yet. Drop or choose a PDF to see the hand-off; the callback here does nothing.">
          <div className="w-full min-w-0">
            <MarkClassSet lastUpload={null} onFiles={noop} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="live" note="MarkClassSet with a last upload">
          <div className="w-full min-w-0">
            <MarkClassSet lastUpload="Year 11 Physics, P4" onFiles={noop} />
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Home: at-risk students"
        summary="Reasons are shown, never a bare red dot. An acknowledged flag reads as handled; an unacknowledged one leads."
      >
        <StateCell wide state="default" provenance="prop" note="AtRiskTable, three students with a grade drop each">
          <div className="w-full min-w-0">
            <AtRiskTable students={FIXTURE_AT_RISK} />
          </div>
        </StateCell>
        <StateCell wide state="success" provenance="prop" note="AtRiskTable, nobody at risk">
          <div className="w-full min-w-0">
            <AtRiskTable students={[]} />
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Teacher setup"
        summary="The first-run home: three steps derived from account data, never from a stored flag. The class code is copyable once a class exists."
      >
        <StateCell wide state="default" provenance="live" note="TeacherSetup, nothing done yet. Choose a PDF to see the nudge toward creating a class first.">
          <div className="w-full min-w-0">
            <TeacherSetup progress={deriveSetup(0, { paperCount: 0, pendingReviewCount: 0 })} firstClass={null} unlocks={unlocksFor([])} onFiles={noop} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="live" note="TeacherSetup, class created, ready for a first upload. Copy the class code.">
          <div className="w-full min-w-0">
            <TeacherSetup progress={deriveSetup(1, { paperCount: 0, pendingReviewCount: 0 })} firstClass={FIXTURE_CLASSES[0]!} unlocks={unlocksFor([FIXTURE_CLASSES[0]!])} onFiles={noop} />
          </div>
        </StateCell>
        <StateCell wide state="default" provenance="prop" note="TeacherSetup, two of three done: papers are in, review is open">
          <div className="w-full min-w-0">
            <TeacherSetup progress={deriveSetup(1, { paperCount: 12, pendingReviewCount: 5 })} firstClass={FIXTURE_CLASSES[0]!} unlocks={unlocksFor([FIXTURE_CLASSES[0]!])} onFiles={noop} />
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Teacher home, all four views"
        summary="The real TeacherHome, fed only by seeded queries. The error view is the in-page banner: its Try again button is a real enabled button in on-error-container over error-container. Pressing it fires a request the preview never answers, so it shows its busy label and stays there; the retry itself cannot complete without a server."
      >
        <StateCell wide state="default" provenance="prop" note="overview">
          <HomeFrame>
            <Seeded seed={HOME_SEEDS.overview}>
              <TeacherHome />
            </Seeded>
          </HomeFrame>
        </StateCell>
        <StateCell wide state="default" provenance="prop" note="setup (one class, no papers)">
          <HomeFrame>
            <Seeded seed={HOME_SEEDS.setup}>
              <TeacherHome />
            </Seeded>
          </HomeFrame>
        </StateCell>
        <StateCell wide state="error" provenance="prop" note="error banner with Try again" >
          <HomeFrame>
            <Seeded seed={HOME_SEEDS.error}>
              <TeacherHome />
            </Seeded>
          </HomeFrame>
        </StateCell>
        <StateCell wide state="loading" provenance="prop" note="loading (the requests never answer, so the slow-load state shows after 5 s)">
          <HomeFrame>
            <Seeded seed={HOME_SEEDS.loading}>
              <TeacherHome />
            </Seeded>
          </HomeFrame>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Settings modal"
        summary="The shell only: a centred dialog with a tab rail on wide screens and scrollable top tabs on phones. Each tab is a router link and each panel is its own route, so the panel content is not rendered here; the frame, the rail built from the real teacher tab list, focus trap and close are."
      >
        <StateCell state="default" provenance="live" note="Open the dialog, Tab through the rail, press Escape to close.">
          <SettingsDemo />
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Empty, error and offline"
        summary="The three state views as the teacher screens use them: a compact cell-sized form and the full panel."
      >
        <StateCell state="default" provenance="prop" note="EmptyState">
          <EmptyState heading="No classes yet" body="Create a class and share its code to get your students marking." action={{ label: "Create a class", onClick: noop }} />
        </StateCell>
        <StateCell state="error" provenance="prop" note="ErrorState with a working action">
          <ErrorState heading="We couldn't load your classes" body="Check your connection and try again." action={{ label: "Try again", onClick: noop }} />
        </StateCell>
        <StateCell state="error" provenance="prop" note="ErrorState, compact: an enabled underlined action inside a table cell or field">
          <ErrorState compact heading="Couldn't load classes" action={{ label: "Try again", onClick: noop }} />
        </StateCell>
        <StateCell state="default" provenance="prop" note="OfflineState">
          <OfflineState heading="You're offline" body="Marks you have already opened are still here. New work waits until you're back online." />
        </StateCell>
      </ComponentSection>
    </Group>
  )
}
