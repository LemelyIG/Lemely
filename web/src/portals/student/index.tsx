/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, Suspense, useEffect, useState } from "react"
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { CalendarBlank, Cards, CaretDown, PencilSimpleLine, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { buttonVariants } from "@/components/ui/button"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { portalErrorFallback } from "@/components/route-error"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { RouteFallback } from "@/components/ui/state-views"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { XPStreak } from "@/components/ui/xp-streak"
import { useProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import type { SubjectRow } from "@/lib/studentTypes"
import { currentSubjectCode, navGroups, resolveCrumbTrail, subjectIcon } from "./data"

/*
 * Student portal (terracotta). Grouped sidebar nav + a sticky top header
 * (breadcrumb, search, streak pill, "Correct a paper" CTA) wrap an <Outlet/>.
 * The layout root sets data-portal="student" so the token layer resolves to the
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
const PaperResult = lazy(() => import("./screens/PaperResult").then((m) => ({ default: m.PaperResult })))
const CorrectPaper = lazy(() => import("./screens/CorrectPaper").then((m) => ({ default: m.CorrectPaper })))
const StudyPlanSession = lazy(() =>
  import("./screens/studyplan/StudyPlanSession").then((m) => ({ default: m.StudyPlanSession })),
)
const StudyPlanWeek = lazy(() =>
  import("./screens/studyplan/StudyPlanWeek").then((m) => ({ default: m.StudyPlanWeek })),
)
const Standings = lazy(() => import("./screens/Standings").then((m) => ({ default: m.Standings })))
const Announcements = lazy(() =>
  import("./screens/Announcements").then((m) => ({ default: m.Announcements })),
)
const Notifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.Notifications })),
)
const Friends = lazy(() => import("./screens/Friends").then((m) => ({ default: m.Friends })))
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

/**
 * Sidebar identity block. Wired to `GET /api/me/profile` (`useProfile()`) —
 * replaces the mock's hardcoded "Maya Rahman / Year 11 - Helwan Science
 * Centre" and "MR" initials, which no field anywhere supplies. This is the
 * same fiction P3.7 chunk b removed from the *teacher* sidebar; the student
 * side was missed then and is fixed here (P3.10 chunk c), reusing that
 * screen's `UserBlock` shape verbatim so the two cannot drift.
 *
 * `displayName` is nullable (a caller who never set one); the fallback is the
 * email's local part, never a fabricated name. The subtitle is the caller's
 * real platform role — the only affiliation-like fact this account actually
 * carries. There is no year-group or school-name field on `Profile`, so no
 * "Year 11 - <school>" line is rendered at all rather than invented.
 */
function UserBlock() {
  const { data, isPending, isError } = useProfile()

  if (isPending || isError || !data) {
    return (
      <div className="flex items-center gap-2.5 px-0.5 text-body-sm text-ink-faint">
        {isPending ? "Loading…" : "Signed in"}
      </div>
    )
  }

  const name = data.displayName ?? data.email.split("@")[0]
  const roleLabel = data.role
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")

  return (
    <div className="flex items-center gap-2.5">
      {/* P4.1: the hand-rolled circle is now the kit's `Avatar`, which is a
          squircle. DESIGN.md §6 reserves the circle for status and live dots
          "so a dot never reads as a person" — and this one sat in a sidebar
          footer directly under eleven circular nav dots, which is the exact
          collision that rule describes. The initials logic it carried was a
          second copy of `Avatar`'s own; two copies of the same fallback is how
          one of them ends up handling a single-word name differently. */}
      <Avatar name={name} size="md" />
      <div className="min-w-0">
        <div className="truncate text-body-sm font-medium text-ink">{name}</div>
        <div className="text-body-sm text-ink-faint">{roleLabel}</div>
      </div>
    </div>
  )
}

/**
 * The grouped destination list itself, with no chrome around it.
 *
 * Extracted from `Sidebar` in P3.1 so the desktop aside and the mobile drawer
 * render the same list from the same code. Two copies would have been the
 * shorter diff and the wrong answer: the whole defect being fixed here is a
 * navigation that exists at one width and not another, and the surest way to
 * reintroduce it is to give each width its own copy of the item list to drift.
 *
 * `touch` raises every row to the 44px minimum Phase 6 requires. It is on in
 * the drawer (a phone, a thumb) and off in the desktop aside, where a 34px row
 * is being clicked with a pointer and eleven 44px rows would push the last of
 * them off a laptop screen.
 */
function NavRow({
  to,
  end,
  label,
  icon: Glyph,
  tag,
  touch,
  indent = false,
  onClick,
}: {
  to: string
  end?: boolean
  label: string
  icon: Icon
  tag?: string
  touch?: boolean
  /** Sub-items nested under a subject's accordion header sit one step in. */
  indent?: boolean
  onClick?: () => void
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          // `px-[9px]` not `pl-`/`pr-`: symmetric padding has no
          // direction, so this row needs no logical rewrite (P3.4).
          // §6.1 touch floor — see the note in nav-shells.tsx.
          "flex items-center gap-2.5 w-full text-start text-label px-[9px] py-2 pointer-coarse:min-h-11 rounded-md",
          "transition-colors duration-[var(--dur-instant)] ease-out-soft",
          // `focus-ring`, not `accent`. DESIGN.md §3.9 makes focus
          // deliberately blue so it stays distinguishable from the
          // accent's own hover and selected states — and this nav is
          // exactly where that matters, since its active row is
          // already accent-marked. The row used `outline-accent`,
          // which made "focused" and "current" the same colour.
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
          // The active rule is reserved at every state, transparent
          // when inactive, so turning it on cannot nudge the label
          // sideways by 2px as you navigate.
          "border-s-2",
          touch && "min-h-11",
          indent && "ps-[30px]",
          isActive
            ? "border-accent bg-paper-raised text-ink"
            : "border-transparent bg-transparent text-ink-muted hover:bg-paper hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* §10 permits `fill` for a single active-state nav icon,
              and this is it. The active row therefore carries four
              independent signals — the accent margin rule, the
              raised sheet, full-strength ink, and the filled glyph —
              so none of them is carrying the state alone. */}
          <Glyph
            size={16}
            weight={isActive ? "fill" : "regular"}
            className={cn("shrink-0", isActive ? "text-accent" : "text-ink-faint")}
            aria-hidden="true"
          />
          <span className="flex-1">{label}</span>
          {tag ? <span className="text-data-sm text-ink-faint">{tag}</span> : null}
        </>
      )}
    </NavLink>
  )
}

/**
 * One subject's accordion row: the subject itself (a `NavRow` to its
 * overview page) plus a chevron toggle, and — when open — its three
 * subject-scoped destinations.
 *
 * The chevron is a separate control from the subject link rather than
 * making the whole header row a button, for the same reason `QuestionRow`
 * keeps its expand toggle beside rather than wrapping its content: a button
 * cannot contain a link (invalid HTML, breaks keyboard/AT semantics), and a
 * student browsing another subject's sub-items without leaving the page
 * they're on needs a control that doesn't navigate.
 */
function SubjectNavGroup({
  subject,
  expanded,
  onToggle,
  onNavigate,
  touch,
}: {
  subject: SubjectRow
  expanded: boolean
  onToggle: () => void
  onNavigate: () => void
  touch?: boolean
}) {
  const Glyph = subjectIcon(subject.code)
  const { data: reference } = useReference()
  const { secondary } = subjectIdentifier(
    reference?.qualificationLevels,
    subject.name,
    subject.code,
    subject.qualificationLevel,
  )
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <NavRow
            to={`/student/subject/${subject.code}`}
            label={subject.name}
            icon={Glyph}
            tag={secondary || undefined}
            touch={touch}
            onClick={onNavigate}
          />
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Collapse" : "Expand"} ${subject.name}`}
          className={cn(
            "flex-none rounded-md p-1.5 text-ink-faint transition-colors",
            "hover:bg-paper hover:text-ink",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
            touch && "min-h-11 min-w-11",
          )}
        >
          <CaretDown
            size={14}
            className={cn("transition-transform duration-[var(--dur-instant)]", expanded && "rotate-180")}
            aria-hidden="true"
          />
        </button>
      </div>
      {expanded ? (
        <div className="flex flex-col gap-0.5">
          <NavRow
            to={`/student/practice/${subject.code}`}
            label="Practice"
            icon={PencilSimpleLine}
            touch={touch}
            indent
          />
          <NavRow
            to={`/student/flashcards/${subject.code}`}
            label="Flashcards"
            icon={Cards}
            touch={touch}
            indent
          />
          <NavRow
            to={`/student/plan/${subject.code}`}
            label="Study plan"
            icon={CalendarBlank}
            touch={touch}
            indent
          />
        </div>
      ) : null}
    </div>
  )
}

/**
 * The grouped destination list itself, with no chrome around it.
 *
 * Extracted from `Sidebar` in P3.1 so the desktop aside and the mobile drawer
 * render the same list from the same code. Two copies would have been the
 * shorter diff and the wrong answer: the whole defect being fixed here is a
 * navigation that exists at one width and not another, and the surest way to
 * reintroduce it is to give each width its own copy of the item list to drift.
 *
 * `touch` raises every row to the 44px minimum Phase 6 requires. It is on in
 * the drawer (a phone, a thumb) and off in the desktop aside, where a 34px row
 * is being clicked with a pointer and eleven 44px rows would push the last of
 * them off a laptop screen.
 *
 * Subjects render as an accordion: at most one open at a time, the one
 * matching the current route opens automatically, and the desktop aside and
 * mobile drawer each own an independent open/closed state since they are
 * separate mounted instances, not two views of one. `useOverview()` is the
 * same query `Overview.tsx` already reads — react-query dedupes the two
 * subscriptions onto one request, so this does not add a second fetch.
 */
function NavGroups({ touch = false }: { touch?: boolean }) {
  const location = useLocation()
  const overview = useOverview()
  const routeSubject = currentSubjectCode(location.pathname)
  const [openCode, setOpenCode] = useState<string | null>(routeSubject)

  // Opens the subject the student navigates into (e.g. from a link on
  // Overview, not just from this sidebar). Deliberately one-directional: it
  // never closes a manually-opened group when the route stops matching a
  // subject, so browsing to a non-subject screen doesn't collapse the
  // subject the student was just looking at.
  useEffect(() => {
    if (routeSubject) setOpenCode(routeSubject)
  }, [routeSubject])

  return (
    <div className="flex flex-col gap-[22px]">
      {navGroups.map((grp) => (
        <div key={grp.label} className="flex flex-col gap-0.5">
          <div className="text-eyebrow text-ink-faint px-2 pb-[7px]">{grp.label}</div>
          {grp.label === "Student" ? (
            <>
              {grp.items.slice(0, 1).map((it) => (
                <NavRow key={it.to} to={it.to} end={it.end} label={it.label} icon={it.icon} touch={touch} />
              ))}
              {overview.data?.subjects.map((subject) => (
                <SubjectNavGroup
                  key={subject.code}
                  subject={subject}
                  expanded={openCode === subject.code}
                  onToggle={() => setOpenCode((prev) => (prev === subject.code ? null : subject.code))}
                  onNavigate={() => setOpenCode(subject.code)}
                  touch={touch}
                />
              ))}
              {grp.items.slice(1).map((it) => (
                <NavRow key={it.to} to={it.to} end={it.end} label={it.label} icon={it.icon} touch={touch} />
              ))}
            </>
          ) : (
            grp.items.map((it) => (
              <NavRow
                key={it.to}
                to={it.to}
                end={it.end}
                label={it.label}
                icon={it.icon}
                tag={it.tag}
                touch={touch}
              />
            ))
          )}
        </div>
      ))}
    </div>
  )
}

/*
 * P3.1: the "Open the teacher portal →" link that used to sit in this footer
 * is gone, and so is its twin in the teacher sidebar. Neither one worked for
 * anybody. `RequireAuth` gates `/teacher` to teacher/school_admin/
 * platform_admin, so a student following it is redirected straight back to
 * `/student` by `portalPathForRole` — and there is no role that holds both, so
 * there was no user for whom either link did anything at all. They are
 * build-era conveniences from before the guard existed, left rendering in the
 * product as two guaranteed dead ends. Role switching for the accounts that
 * genuinely hold two roles is a real feature and is not this.
 */

/*
 * The real mark, replacing the accent dot that stood in for it (audit M9: "the
 * logo is a lowercase italic *l* in a filled circle, stamped in three places"
 * — the student sidebar's dot was a fourth variant of the same placeholder).
 * `web/public/brand/mark.svg` is the asset Phase 2 authored.
 *
 * `alt=""` and `aria-hidden`, not a described image: the wordmark beside it
 * already says "Lemely", so describing the mark too makes a screen reader
 * announce the brand twice. The mark file carries its own <title>, which is
 * correct when it is used standalone (the favicon) and is suppressed here.
 */
function BrandLockup() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
      <span className="text-display-sm text-ink">Lemely</span>
    </div>
  )
}

function Sidebar() {
  return (
    // A well, per DESIGN.md §3.1: `--paper-sunk` is the token whose stated use
    // is "sidebars, table headers, code blocks, inset areas". Same value the
    // build-era `bg-surface-2` alias resolved to; this is the name the system
    // actually defines.
    <aside className="hidden min-[820px]:flex w-[246px] flex-none bg-paper-sunk border-e border-rule px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <BrandLockup />

      <nav aria-label="Student sections" className="overflow-auto lm-scroll">
        <NavGroups />
      </nav>

      <div className="mt-auto border-t border-rule pt-[14px]">
        <UserBlock />
      </div>
    </aside>
  )
}

/**
 * The streak pill, restored — this time from data that exists.
 *
 * P3.10 chunk c deleted a "24 day streak" pill from this header because the 24
 * was a literal, and recorded the reason it was not simply rewired: the only
 * streak-shaped field in the API at the time was `StandingsDTO.streakDays`,
 * which counts *distinct active days* rather than consecutive ones, so wiring
 * the pill to it "would have replaced a hardcoded lie with a mislabelled one".
 * Its closing note was "streaks are Phase 5's to build for real". Phase 5 built
 * them: `GET /api/student/xp` returns a genuine consecutive-day `streak.current`
 * alongside `totalXp`, and this reads those.
 *
 * Three constraints on it, each the reason a line of this is written the way it
 * is:
 *
 * - **Nothing renders until the read lands, and nothing renders if it fails.**
 *   No placeholder, no skeleton, no zero. A pill is chrome, so an absent pill
 *   costs the student nothing, while a `0` while loading would state a broken
 *   streak they may not have.
 * - **Hidden below 640px.** This row's fixed items already overflowed a 380px
 *   viewport once (see the note in `Header`), and a pill is exactly the kind of
 *   thing that would put it back over. The figure is not lost on a phone: it is
 *   the hero of the training log, one tap away in the nav.
 * - **It is a `<Link>`, not decoration.** A number a student is invited to care
 *   about should go somewhere when tapped, and the place it explains itself is
 *   the training log.
 */
function HeaderStreak() {
  const xp = useXpProfile()
  /*
   * Shape-checked, not just presence-checked, and that is not defensive
   * programming for its own sake. This component renders in the shell above
   * all twenty-four student routes, so `xp.data.streak.current` on a body that
   * came back without a `streak` would throw inside the header and take the
   * whole portal down — every screen, not just this pill. `request<XpProfile>`
   * is a cast, not a validation, so the type says nothing about what actually
   * arrived. Found while stubbing this surface's captures, where the harness's
   * catch-all answers unmatched calls with `{}`: exactly that body, and
   * exactly that crash.
   */
  const streak = xp.data?.streak?.current
  const total = xp.data?.totalXp
  if (typeof streak !== "number" || typeof total !== "number") return null
  return (
    <Link
      to="/student/profile"
      aria-label={`Your training log: ${streak} day streak, ${total} XP`}
      className="hidden flex-none min-[640px]:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"
    >
      <XPStreak variant="compact" streakDays={streak} xpTotal={total} />
    </Link>
  )
}

function Header({ onOpenNav }: { onOpenNav: () => void }) {
  const location = useLocation()
  const trail = resolveCrumbTrail(location.pathname)
  const onCorrectScreen = location.pathname === "/student/correct"
  return (
    // Responsive sizing here is load-bearing, not cosmetic: this row's fixed
    // items (34px padding either side, the 138px CTA and the gaps) overflowed
    // a 380px viewport on /student/result — a real QUALITY-BAR "no horizontal
    // scroll from 320px up" failure, found by P3.10 chunk b's responsive gate
    // once it covered this route. The crumb must still be able to shrink
    // (`min-w-0 truncate`; it renders "Home / Result <uuid>", the longest
    // string on the row) and the padding still tightens below 640px.
    //
    // P3.10 chunk c removed two of the fixed items this row used to carry, so
    // it now has considerably more slack than the fix above needed:
    //   - a `<span>` styled as a search input ("Search papers, topics,
    //     students"). It was not an input, had no handler, and no search
    //     endpoint exists anywhere in the API — fabricated UI.
    //   - a "24 day streak" pill, where the 24 was a literal. The only
    //     streak-shaped field in the API is `StandingsDTO.streakDays`, and
    //     that is `len({distinct dates in history})` — a count of active
    //     days, NOT consecutive ones. Wiring the pill to it would have
    //     replaced a hardcoded lie with a mislabelled one, so the pill is
    //     gone instead; streaks are Phase 5's to build for real.
    // `backdrop-blur` on a *fixed* bar is the one glassmorphism exception
    // DESIGN.md §7 permits, and this is that bar. `z-nav` replaces the raw
    // `z-20`: same number, but the z-index scale is a gate and a literal
    // bypasses it.
    <header className="flex items-center gap-[18px] px-page-mobile min-[640px]:px-page-desktop py-4 border-b border-rule bg-paper/80 backdrop-blur-nav sticky top-0 z-nav">
      {/* P3.1: the only navigation entry point below 820px, which is where the
          sidebar stops existing. `-ms-2` pulls the 44px target back level with
          the crumb's text edge without shrinking the target itself. */}
      <NavDrawerTrigger
        onClick={onOpenNav}
        label="Open student navigation"
        className="-ms-2 min-[820px]:hidden"
      />
      {/* P4.1: the inert mono string is now the same `Breadcrumbs` trail D1.5
          gave the teacher and parent portals, so a student drilled into a
          subject, a result or a plan session has a route back that is not the
          browser's own gesture. `text-metadata` was also the wrong rung: the
          mono `data-sm` scale is scoped to paper codes, IDs and timestamps,
          and a crumb label is none of those — it is words a reader reads. */}
      <Breadcrumbs items={trail} className="flex-1" />
      <HeaderStreak />
      {/*
       * P4.2, two corrections to one control.
       *
       * It was a `<Button onClick={navigate(...)}>` for a pure navigation —
       * the identical finding D4.1 fixed on the dashboard's subject rows
       * (audit M8), sitting unremarked in the shell that renders above every
       * student screen. As a button it could not be middle-clicked, opened in
       * a new tab, copied as a link or previewed, and it announced to
       * assistive technology that something would happen rather than that
       * somewhere would be reached.
       *
       * And it rendered on `/student/correct` itself, where pressing it does
       * nothing observable: the product's single most prominent call to
       * action was a dead control on the one screen it points at.
       */}
      {onCorrectScreen ? null : (
        <Link
          to="/student/correct"
          className={buttonVariants({ variant: "primary", size: "md" })}
        >
          Correct a paper
        </Link>
      )}
    </header>
  )
}

// One boundary around the Outlet, not one per <Route element>: the sidebar,
// header and chrome above stay mounted and interactive while a screen chunk
// downloads, so navigating never blanks the whole page — only the content
// slot shows the loading state, then swaps to the real screen. Matches the
// "Loading…" `role="status"` text every screen below already uses for its own
// data-pending state (see e.g. `screens/Overview.tsx`), so a chunk load reads
// as the same kind of wait, not a new visual language. The fallback itself is
// `RouteFallback` from the C-11 state-view family — one shared component, since
// all three portals and `App.tsx` need it and four local copies had already
// drifted to three different type/padding combinations before they were merged.

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
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const queryClient = useQueryClient()

  /*
   * The wiring for `studentOnboardingRedirect` above: `useStudentProfile()`
   * reads the S-02 record onboarding itself writes (`useProfile()` in
   * `UserBlock` above is a different endpoint, `/me/profile`, whose
   * `Profile` type carries no onboarding field at all).
   *
   * A pending query renders the shared route fallback in place of the whole
   * shell rather than the shell with a fallback inside it: until the profile
   * resolves we do not yet know whether this student belongs on this route,
   * so there is nothing honest to put in a sidebar built for a destination
   * we might immediately redirect away from. An errored or a
   * resolved-and-complete query both fall through to the portal exactly as
   * it rendered before this gate existed — an errored profile fetch must
   * degrade to "the portal renders", never to "the account is stuck on
   * onboarding until the network recovers".
   */
  const studentProfile = useStudentProfile()
  if (studentProfile.isPending) {
    return <RouteFallback className="p-8" />
  }
  const onboardingRedirect = studentOnboardingRedirect(
    studentProfile.status,
    studentProfile.data?.profile.onboardingCompletedAt ?? null,
    location.pathname,
  )
  if (onboardingRedirect) {
    return <Navigate to={onboardingRedirect} replace />
  }

  return (
    // `paper-grain` (DESIGN.md §8.1): one fixed, pointer-events-none noise
    // overlay at 0.035 opacity across the whole portal. This is the cheapest
    // and most durable way the one protected quality — the notebook feel —
    // reaches every student screen, including the ~20 this surface does not
    // touch. It is fixed rather than scrolled precisely so it never repaints
    // on scroll on the mid-range Android phones §7 keeps naming.
    <div data-portal="student" className="paper-grain flex min-h-screen">
      <SkipLink />
      <Sidebar />

      {/* Same list, same source, different chrome — see `NavGroups`. The
          drawer closes itself on navigation, so nothing here has to. */}
      <NavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="Lemely"
        footer={<UserBlock />}
      >
        <nav aria-label="Student sections">
          <NavGroups touch />
        </nav>
      </NavDrawer>

      <div className="flex-1 min-w-0 flex flex-col">
        <Header onOpenNav={() => setNavOpen(true)} />
        {/* `<main>` moved inward in P3.1. It used to wrap the header as well,
            which made the skip link's target include the navigation it exists
            to skip past, and gave the page two competing landmarks for "the
            content". The header is chrome; `main` is what the route rendered. */}
        {/* Container and gutters are now the ones DESIGN.md §5 defines for
            the Operate lane — 1200px content max (`max-w-app`), and a page
            gutter that steps 16 / 20 / 32px rather than sitting at a flat
            34px from 320px upward. The old `p-[34px]` spent 68px of a 375px
            phone on margin, which is 18% of the viewport given to nothing. */}
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="flex-1 w-full max-w-app px-page-mobile py-6 md:px-page-tablet lg:px-page-desktop lg:py-8 focus:outline-none"
        >
          {/* PR 2 part C: offline recovery banner, above the Suspense/
              ErrorBoundary content it sits over — it renders nothing while
              online, so its own `mb-6` is the only spacing this adds. */}
          <OfflineBanner
            onRetry={() =>
              void queryClient.refetchQueries({
                type: "active",
                predicate: (query) => query.state.status === "error",
              })
            }
          />
          <Suspense fallback={<RouteFallback className="text-body-md" />}>
            {/* PR 1B fulfils the note above ("Phase 4 places those as it
                rebuilds each surface", `routes.tsx`): a render crash in one
                screen now stays inside this content slot instead of taking
                the sidebar/header down with it or falling out to the
                top-level `errorElement`. Inside `Suspense`, not outside it,
                so a failed chunk load and a render throw both land in this
                boundary while the chrome stays painted.
                `resetKey={location.pathname}` clears a caught error on
                navigation — a crash on `/student/board` must not still be
                showing once the reader is on `/student/friends`. */}
            <ErrorBoundary
              label="This page"
              resetKey={location.pathname}
              fallback={portalErrorFallback}
            >
              <Outlet />
            </ErrorBoundary>
          </Suspense>
        </main>
      </div>
    </div>
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
    { index: true, element: <Overview />, handle: { title: "Dashboard" } },
    { path: "subject/:code", element: <Subject />, handle: { title: "Subject" } },
    { path: "result/:paperId", element: <PaperResult />, handle: { title: "Paper result" } },
    { path: "correct", element: <CorrectPaper />, handle: { title: "Mark a paper" } },
    { path: "plan/:subjectCode", element: <StudyPlanWeek />, handle: { title: "Study plan" } },
    {
      path: "plan/:subjectCode/session/:sessionId",
      element: <StudyPlanSession />,
      handle: { title: "Study session" },
    },
    { path: "board", element: <Standings />, handle: { title: "Leaderboard" } },
    { path: "announcements", element: <Announcements />, handle: { title: "Announcements" } },
    { path: "notifications", element: <Notifications />, handle: { title: "Notifications" } },
    { path: "friends", element: <Friends />, handle: { title: "Friends" } },
    { path: "profile", element: <Profile />, handle: { title: "Your profile" } },
    // The only place a parent_child_links row is created (D3.11).
    { path: "parents", element: <Parents />, handle: { title: "Parent access" } },
    { path: "onboard", element: <Onboarding />, handle: { title: "Getting set up" } },
    {
      path: "placement/:subjectCode",
      element: <PlacementInvite />,
      handle: { title: "Placement test" },
    },
    {
      path: "placement/test/:assignmentId",
      element: <PlacementTest />,
      handle: { title: "Placement test" },
    },
    {
      path: "placement/result/:assignmentId",
      element: <PlacementResult />,
      handle: { title: "Placement result" },
    },
    {
      path: "practice/:subjectCode",
      element: <PracticeGenerator />,
      handle: { title: "New practice set" },
    },
    { path: "practice/set/:assignmentId", element: <PracticeSet />, handle: { title: "Practice" } },
    {
      path: "practice/result/:assignmentId",
      element: <PracticeResult />,
      handle: { title: "Practice result" },
    },
    {
      path: "practice/print/:assignmentId",
      element: <PracticePrint />,
      handle: { title: "Print practice set" },
    },
    {
      path: "flashcards/:subjectCode",
      element: <FlashcardDecks />,
      handle: { title: "Flashcards" },
    },
    {
      path: "flashcards/review/:subjectCode",
      element: <FlashcardReview />,
      handle: { title: "Flashcard review" },
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
    { path: "landing", element: <Navigate to="/landing" replace />, handle: { title: "Lemely" } },
    /*
     * P4.10. Last, so it only matches what nothing above did. Before this, an
     * unmatched path inside this portal fell through to the top-level `*` and
     * the reader lost the sidebar, the header and the trail on a typo. See
     * `portals/misc/NotFound.tsx` for why it is a separate component and not
     * the standalone screen.
     */
    { path: "*", element: <PortalNotFound />, handle: { title: "Page not found" } },
  ],
}
