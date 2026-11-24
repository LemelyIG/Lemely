/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { useState } from "react"
import { GhostRows } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { useFriends } from "@/lib/hooks/useFriendApi"
import { useLeaderboard, useMyClasses } from "@/lib/hooks/useLeaderboardApi"
import { useProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useDeletedPapers } from "@/lib/hooks/usePaperDeletionApi"
import { useParentLinks } from "@/lib/hooks/useStudentApi"
import { useStudentHome } from "@/lib/hooks/useStudentHomeApi"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { AccountRows } from "./AccountRows"
import { BadgeRow } from "./BadgeRow"
import { BadgesSheet } from "./BadgesSheet"
import { MeHero } from "./MeHero"
import { accountRows, activityVm, deriveBadges, heroName, peopleVm, resolveRankingsOff, statsVm, subjectsVm } from "./meModel"
import { MeSkeleton } from "./MeSkeleton"
import { PeopleDoors } from "./PeopleDoors"
import { ProgressSheet } from "./ProgressSheet"
import { RecentActivity } from "./RecentActivity"
import { StatsRow } from "./StatsRow"
import { StreakStrip } from "./StreakStrip"
import { YourSubjects } from "./YourSubjects"

const COL = "contents md:flex md:min-w-0 md:flex-col md:gap-[18px]"

export function MeScreen() {
  const xp = useXpProfile()
  const me = useProfile()
  const home = useStudentHome()
  const classes = useMyClasses()
  const firstClass = classes.data?.classes[0]?.classId
  const board = useLeaderboard({ scope: "class", basis: "total", classId: firstClass })
  const studentProfile = useStudentProfile()
  const rankingsOff = resolveRankingsOff({
    profileOptOut: studentProfile.data?.profile.leaderboardOptOut,
    boardOptedOut: board.data?.viewerOptedOut,
    profileFailed: studentProfile.isError,
  })
  const friends = useFriends()
  const parents = useParentLinks()
  const deleted = useDeletedPapers()
  const overlayState = useOverlayState()
  const [sheet, setSheet] = useState<null | "progress" | "badges">(null)
  const openSheet = (which: "progress" | "badges") => () => setSheet(which)
  const name = heroName(me.data)

  const homePart = (render: (h: NonNullable<typeof home.data>) => React.ReactNode, order: string) =>
    home.data ? (
      <div className={order}>{render(home.data)}</div>
    ) : home.isError ? (
      <button type="button" onClick={() => void home.refetch()} className={`${order} min-h-11 text-start text-[13px] font-semibold text-primary`}>
        Couldn't load this part. Try again
      </button>
    ) : (
      <div className={order}>
        <GhostRows rows={2} announce={false} />
      </div>
    )

  return (
    <div className="flex flex-col gap-[22px] pb-24 md:pb-8">
      <header className="flex items-center gap-5">
        <PageHeading repeatsTitle className="sr-only md:not-sr-only md:flex-1 md:font-display md:text-[32px] md:font-extrabold md:leading-[1.1] md:tracking-[-0.03em] md:text-primary">
          Me
        </PageHeading>
      </header>
      {!home.data && !home.isError && xp.data ? <span className="sr-only" role="status">Loading</span> : null}
      <QueryState
        query={xp}
        skeleton={<MeSkeleton />}
        error={{
          heading: "Your XP could not be loaded",
          body: "This is a connection problem. Your XP and streak are safe, and nothing has been lost.",
          marginalia: "Nothing you earned is lost",
        }}
      >
        {(profile) => (
          <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-12">
            <div className={COL}>
              <MeHero className="order-1 md:order-none" name={name} xp={profile} avatarUrl={me.data?.avatarUrl ?? null} />
              <StreakStrip className="order-2 md:order-none" xp={profile} onOpen={openSheet("progress")} />
              {homePart((h) => <StatsRow stats={statsVm(h)} />, "order-3 md:order-none")}
              {homePart((h) => <BadgeRow badges={deriveBadges(h, profile)} onAll={openSheet("badges")} />, "order-5 md:order-none")}
              {homePart((h) => <YourSubjects rows={subjectsVm(h)} />, "order-6 md:order-none")}
            </div>
            <div className={COL}>
              <PeopleDoors
                className="order-4 md:order-none"
                doors={peopleVm({
                  classes: classes.data?.classes.length,
                  rank: firstClass ? (board.data ? (board.data.viewer?.rank ?? null) : undefined) : null,
                  rankingsOff,
                  friends: friends.data?.friends.length,
                  parents: parents.data?.parents.length,
                })}
              />
              {homePart((h) => <RecentActivity rows={activityVm(h)} />, "order-7 md:order-none")}
              <AccountRows
                className="order-8 md:order-none"
                rows={accountRows({ deletedCount: deleted.data?.papers.length, placementCode: home.data?.floor[0]?.code ?? null })}
                overlayState={overlayState}
              />
            </div>
          </div>
        )}
      </QueryState>
      <ProgressSheet open={sheet === "progress"} onOpenChange={(o) => setSheet(o ? "progress" : null)} xp={xp.data} />
      <BadgesSheet

        open={sheet === "badges"}
        onOpenChange={(o) => setSheet(o ? "badges" : null)}
        badges={home.data && xp.data ? deriveBadges(home.data, xp.data) : []}
      />
    </div>
  )
}
