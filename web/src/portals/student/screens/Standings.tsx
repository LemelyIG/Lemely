import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Fire } from "@phosphor-icons/react"
import {
  useLeaderboard,
  useMyClasses,
} from "@/lib/hooks/useLeaderboardApi"
import { usePatchStudentProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useStandings } from "@/lib/hooks/useStudentApi"
import type {
  Leaderboard,
  LeaderboardRow,
  LeaderboardScope,
} from "@/lib/leaderboardTypes"
import { cn } from "@/lib/utils"
import { vizText } from "../components/colors"

/*
 * S-29 · Leaderboards (P5.8 chunk C).
 *
 * This screen replaces the honest-empty placeholder that stood here since
 * P2.7. Its header comment recorded that the friends/school/global boards were
 * *deliberately removed rather than mocked*, because `StandingsDTO` had no
 * `boards` field and no backend existed. Both now exist
 * (`GET /api/student/leaderboard`, all four scopes), so the boards are real.
 * **The subject standings that placeholder did carry is real data and is kept**
 * — it answers a different question (how am I doing per subject, over all time)
 * from the weekly XP boards, and throwing it away would be a regression.
 *
 * **The hard rule, restated where someone editing this file will see it
 * (UI spec §S-29): no grade, mark, percentage or predicted grade appears on
 * this screen in any form.** That is not merely policy here — the DTOs
 * structurally cannot carry one (D5.1 §0), so there is nothing to render even
 * if someone tried. If you find yourself building a "top performers" section
 * off marks, stop.
 *
 * **Absent is not zero.** A row's `streak` is `null` when the student has no
 * `streaks` row at all, and `0` when they had one and broke it (D5.14 §2). The
 * first renders as nothing; only the second renders a number. Rendering `null`
 * as "0 days" would state something about a student the database has never
 * recorded (UI spec §1.4).
 */

/* ── Week boundary ──────────────────────────────────────────────────────── */

/**
 * Whole civil days from today to the week's last day, inclusive of today.
 *
 * Civil days, not hours — `weekEnd` is a date and carries no time, so an
 * hour-precise countdown would be precision the wire does not have. Same
 * reasoning as S-28's `daysUntil` (chunk B): a boundary a student watches must
 * not move while they sleep.
 */
export function daysLeftInWeek(weekEnd: string, today: Date): number {
  const end = new Date(`${weekEnd}T00:00:00`)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((end.getTime() - start.getTime()) / 86_400_000)
}

export function formatWeekReset(days: number): string {
  if (days <= 0) return "Resets today"
  if (days === 1) return "Resets tomorrow"
  return `Resets in ${days} days`
}

/* ── Identity ───────────────────────────────────────────────────────────── */

/**
 * The first letter of a display name, for the row monogram.
 *
 * A monogram rather than an avatar because **nothing in this schema stores
 * one** (D5.14 §3) — no image, no URL, no colour preference. A generated
 * identicon would look like stored identity the account does not have. Falls
 * back to a neutral glyph for the `"Student"` placeholder D5.5 installed for
 * users who never set a display name, and for any name whose first character
 * is not a letter.
 */
export function monogram(displayName: string): string {
  const first = displayName.trim().charAt(0)
  return /\p{L}/u.test(first) ? first.toUpperCase() : "·"
}

/* ── Rows ───────────────────────────────────────────────────────────────── */

function Monogram({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-surface-2 text-2xs font-medium text-t2"
    >
      {monogram(name)}
    </span>
  )
}

/**
 * A streak, or nothing at all.
 *
 * `null` renders nothing — see this file's header. `0` renders as a real "0",
 * because a student who broke a streak has genuinely broken it and hiding that
 * would be its own small dishonesty.
 */
function StreakBadge({ streak }: { streak: number | null }) {
  if (streak === null) return null
  return (
    <span className="flex items-center gap-1 text-2xs text-t3">
      <Fire size={12} weight="fill" className="text-accent" aria-hidden="true" />
      <span>
        {streak}
        <span className="sr-only"> day streak</span>
      </span>
    </span>
  )
}

function BoardRow({
  row,
  isViewer,
  as: Root = "div",
}: {
  row: Pick<LeaderboardRow, "displayName" | "xp" | "streak"> & {
    rank: number | null
  }
  isViewer: boolean
  /* The ranked board is an ordered list, so its rows are `<li>` — that is the
     honest markup for a ranking and it is what makes row order readable by
     assistive tech (and, incidentally, by `getByRole("listitem")`).
     But this same component also renders the viewer's PINNED row, which sits
     outside the `<ol>` on purpose: its rank is out of sequence with the list
     above it. An `<li>` there would be a listitem with no list parent — a
     serious `listitem` violation under axe's default ruleset, which
     `/student/board` is audited against. Hence an element prop rather than a
     wrapper around the whole body: the two call sites genuinely differ. */
  as?: "li" | "div"
}) {
  return (
    <Root
      className={cn(
        "flex items-center gap-3 py-2.5",
        // The viewer's own row carries a tint *and* the "You" label below, so
        // the "no meaning by colour alone" rule is satisfied by the text, not
        // by a stripe. An earlier cut added a left accent border as a third
        // channel; it was redundant with both and is the single most
        // recognisable tell of a generated interface, so the tint stands alone.
        isViewer && "-mx-3 rounded-md bg-accent-subtle px-3",
      )}
    >
      <span className="w-7 flex-none font-mono text-2xs text-t3">
        {/* A null rank is a real state — the viewer has no XP this week, or has
            opted out. An invented "—" position would be a fabricated last
            place (UI spec §1.4). */}
        {row.rank === null ? "—" : row.rank}
      </span>
      <Monogram name={row.displayName} />
      <span className="min-w-0 flex-1 truncate text-body-md text-t1">
        {row.displayName}
        {isViewer ? <span className="ml-2 text-2xs text-t3">You</span> : null}
      </span>
      <StreakBadge streak={row.streak} />
      <span className="w-16 flex-none text-right font-mono text-dense-lg text-t1">
        {row.xp.toLocaleString()}
        <span className="ml-1 text-3xs text-t3">XP</span>
      </span>
    </Root>
  )
}

/* ── Board ──────────────────────────────────────────────────────────────── */

function BoardBody({
  board,
  scope,
}: {
  board: Leaderboard
  scope: LeaderboardScope
}) {
  if (board.status === "unavailable") {
    // The one modelled unavailable reason, and it is not an error: this student
    // holds no school seat, so a school board has nothing to rank them
    // against. An empty board here would assert "nobody at your school scored
    // this week", which is a different and untrue claim.
    return (
      <EmptyState
        heading="You are not part of a school yet"
        body="School boards rank you against everyone at your school. Your class, friends and global boards all still work."
      />
    )
  }

  const viewerInRows =
    board.viewer !== null &&
    board.rows.some((row) => row.userId === board.viewer?.userId)

  return (
    <div className="flex flex-col">
      {board.rows.length === 0 ? (
        <EmptyState
          heading={
            scope === "friends"
              ? "Nobody has earned XP yet this week"
              : "No XP earned here yet this week"
          }
          body="Correct a paper, review flashcards or finish a study session — the board fills as soon as anyone does."
        />
      ) : (
        <ol className="divide-y divide-border">
          {board.rows.map((row) => (
            <BoardRow
              key={row.userId}
              as="li"
              row={row}
              isViewer={row.userId === board.viewer?.userId}
            />
          ))}
        </ol>
      )}

      {/* The viewer's row stays pinned below when they fall outside the top N,
          so "where am I" is always answerable without paging. Suppressed when
          they are already visible above, which would otherwise show them
          twice. */}
      {board.viewer !== null && !viewerInRows ? (
        <div className="mt-2 border-t border-border pt-2">
          <BoardRow row={board.viewer} isViewer />
          {board.viewerOptedOut ? (
            <p className="pt-1 text-2xs text-t3">
              Your XP is still counted and still yours to see — you are just
              hidden from everyone else's board.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/* ── Opt-out ────────────────────────────────────────────────────────────── */

/**
 * The opt-out control, on the board it governs.
 *
 * UI spec §S-29 requires this be "available and easy to find — this matters
 * for students who find ranking stressful", so it is not buried in a settings
 * screen two navigations away (D5.14 §4).
 */
function OptOutControl() {
  const { data, isPending, isError } = useStudentProfile()
  const patch = usePatchStudentProfile()

  // No control at all rather than a control defaulted to "visible": guessing
  // wrong in that direction shows a student on a public board they may have
  // asked to leave.
  if (isPending || isError || !data) return null

  const optedOut = data.profile.leaderboardOptOut
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-3.5 py-3">
      <div className="min-w-0">
        <p className="text-body-md text-t1">
          {optedOut ? "You are hidden from other students" : "You appear on public boards"}
        </p>
        <p className="text-2xs text-t3">
          {optedOut
            ? "Nobody else sees your name or XP. You still see every board, and you still earn XP."
            : "Other students can see your display name, weekly XP and streak. Never your marks or grades."}
        </p>
      </div>
      <Button
        variant="secondary"
        size="sm"
        // Always a real boolean, never `null`: the column is NOT NULL, so an
        // explicit null is a 422 rather than a coerced false.
        onClick={() => patch.mutate({ leaderboardOptOut: !optedOut })}
        disabled={patch.isPending}
        className="flex-none"
      >
        {optedOut ? "Show me again" : "Hide me"}
      </Button>
    </div>
  )
}

/* ── Scope + basis selectors ────────────────────────────────────────────── */

const SCOPES: { value: LeaderboardScope; label: string }[] = [
  { value: "friends", label: "Friends" },
  { value: "class", label: "Class" },
  { value: "school", label: "School" },
  { value: "global", label: "Everyone" },
]

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-md border px-3 py-1.5 text-2xs transition-colors",
        active
          ? "border-accent bg-accent-subtle text-accent"
          : "border-border bg-surface text-t2 hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  )
}

/* ── Screen ─────────────────────────────────────────────────────────────── */

export function Standings() {
  const navigate = useNavigate()
  const today = useMemo(() => new Date(), [])
  const [scope, setScope] = useState<LeaderboardScope>("friends")
  const [basis, setBasis] = useState<string>("total")
  const [classId, setClassId] = useState<string | null>(null)

  const classes = useMyClasses()
  const profile = useStudentProfile()
  const standings = useStandings()

  const classList = classes.data?.classes ?? []
  // Default to the first class rather than making the student pick before they
  // can see anything. `classId` (the explicit choice) is deliberately NOT what
  // the query receives: a class board with a null id is disabled, and a
  // disabled query stays `isPending` forever — the screen would sit on
  // "Loading the board…" with nothing loading.
  const effectiveClassId = classId ?? classList[0]?.classId ?? null

  const board = useLeaderboard({ scope, basis, classId: effectiveClassId })

  // The basis options are the student's own declared subjects, not a global
  // catalogue: a board for a subject they do not sit is noise they cannot act
  // on (D5.14 §4's reasoning applied to the second selector).
  const subjects = profile.data?.enrolments.map((e) => e.subjectCode) ?? []

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <Eyebrow>Standings</Eyebrow>
        <h1 className="text-display">Effort, not marks</h1>
        <p className="text-body-md text-t2">
          Boards rank XP — the work you put in. Nobody here can see anyone's
          grades.
        </p>
      </header>

      <OptOutControl />

      <section className="flex flex-col gap-4" aria-labelledby="s29-board">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="s29-board" className="text-body-lg font-medium text-t1">
            This week
          </h2>
          {board.data ? (
            <Chip tone="neutral">
              {formatWeekReset(daysLeftInWeek(board.data.weekEnd, today))}
            </Chip>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Board scope">
          {SCOPES.map((s) => (
            <TabButton
              key={s.value}
              active={scope === s.value}
              onClick={() => setScope(s.value)}
            >
              {s.label}
            </TabButton>
          ))}
        </div>

        {/* Only rendered for the class scope, and only when there is a choice
            to make — a selector with one option is a decision the student does
            not have. */}
        {scope === "class" && classList.length > 1 ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Class">
            {classList.map((c) => (
              <TabButton
                key={c.classId}
                active={effectiveClassId === c.classId}
                onClick={() => setClassId(c.classId)}
              >
                {c.name}
              </TabButton>
            ))}
          </div>
        ) : null}

        {subjects.length > 0 ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="XP basis">
            <TabButton active={basis === "total"} onClick={() => setBasis("total")}>
              All subjects
            </TabButton>
            {subjects.map((code) => (
              <TabButton
                key={code}
                active={basis === code}
                onClick={() => setBasis(code)}
              >
                {code}
              </TabButton>
            ))}
          </div>
        ) : null}

        <Card>
          <CardBody>
            {scope === "class" && classList.length === 0 && !classes.isPending ? (
              <EmptyState
                heading="You are not in a class yet"
                body="Class boards rank you against your classmates. Ask your teacher for a join code, or try the friends board."
              />
            ) : board.isError ? (
              <ErrorState
                heading="The board could not be loaded"
                body="This is a connection problem, not an empty board — your classmates' XP is still there."
                action={{ label: "Try again", onClick: () => void board.refetch() }}
              />
            ) : board.isPending || !board.data ? (
              <div className="text-body-md text-t3">Loading the board…</div>
            ) : (
              <BoardBody
                board={board.data}
                scope={scope}
              />
            )}
          </CardBody>
        </Card>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate("/student/friends")}
          >
            Add friends
          </Button>
        </div>
      </section>

      {/* Kept from the screen this replaced: real `subjectRanks` data, and a
          different question from the weekly boards. */}
      <section className="flex flex-col gap-3" aria-labelledby="s29-subjects">
        <h2 id="s29-subjects" className="text-body-lg font-medium text-t1">
          Your subjects
        </h2>
        <Card>
          <CardBody>
            {standings.isError ? (
              <ErrorState
                heading="Subject standings could not be loaded"
                body="A connection problem — nothing has changed about your subjects."
                action={{
                  label: "Try again",
                  onClick: () => void standings.refetch(),
                }}
              />
            ) : standings.isPending || !standings.data ? (
              <div className="text-body-md text-t3">Loading your subjects…</div>
            ) : standings.data.subjectRanks.length === 0 ? (
              <EmptyState
                heading="No subjects ranked yet"
                body="Correct a paper and your subjects appear here."
              />
            ) : (
              <div className="flex flex-col gap-2.5">
                {standings.data.subjectRanks.map((s) => (
                  <div key={s.code} className="flex items-center gap-3">
                    <span className="w-11 flex-none font-mono text-2xs text-t3">
                      {s.code}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-body-md text-t1">
                      {s.name}
                    </span>
                    <span className="text-2xs text-t3">{s.papers} papers</span>
                    <span
                      className={`w-10 flex-none text-right font-mono text-dense-lg ${vizText(s.color)}`}
                    >
                      {s.rank}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </section>
    </div>
  )
}
