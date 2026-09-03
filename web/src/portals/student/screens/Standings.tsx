/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { CountUp } from "@/components/ui/celebration"
import { Fire } from "@phosphor-icons/react"
import {
  useLeaderboard,
  useMyClasses,
} from "@/lib/hooks/useLeaderboardApi"
import { usePatchStudentProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useStandings } from "@/lib/hooks/useStudentApi"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
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
 *
 * ── P4.4, the Study Notebook pass ────────────────────────────────────────
 *
 * **§9.3 names "a leaderboard climb" as one of the five celebration moments,
 * and this screen deliberately does not have one.** `LeaderboardRow.rank` and
 * `LeaderboardViewer.rank` are the only rank fields on the wire and both are
 * the *current* rank; nothing records where the student stood before. A climb
 * flourish would therefore have to invent the movement it congratulates, on a
 * screen whose header comment already forbids inventing a last place. The
 * register is applied to the one thing here that is genuinely observed
 * changing — the viewer's own XP, counted up when a refetch brings a larger
 * number while they are watching. Recorded as a gap in D4.4; it needs a
 * `previousRank` on the DTO, not a client-side guess.
 *
 * The other boards' rows do **not** count up. A dozen numbers animating at
 * once on a ranking is a fireworks display, not a reading aid, and §9.3
 * rations the register to the reader's own wins.
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
      className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-paper-sunk text-eyebrow text-ink-muted"
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
    <span className="flex items-center gap-1 text-data-sm text-ink-faint">
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
  /*
   * P6.4. `--ink-faint` measures **4.47:1 on `--accent-wash`** where AA needs
   * 4.5, so the viewer's own row — the one row that carries the tint — put its
   * de-emphasised text just under the floor (axe `color-contrast`, 2 nodes on
   * `student-standings`). It is fine on paper (5.12:1), which is why nothing
   * caught it: the pairing that fails only exists on one variant of this row.
   * `--ink-muted` is 5.51:1 on the wash and stays de-emphasised.
   */
  const faint = isViewer ? "text-ink-muted" : "text-ink-faint"

  return (
    <Root
      className={cn(
        "flex items-center gap-3 py-2.5",
        // The viewer's own row carries a tint *and* the "You" label below, so
        // the "no meaning by colour alone" rule is satisfied by the text, not
        // by a stripe. An earlier cut added a left accent border as a third
        // channel; it was redundant with both and is the single most
        // recognisable tell of a generated interface, so the tint stands alone.
        isViewer && "-mx-3 rounded-md bg-accent-wash px-3",
      )}
    >
      <span className={cn("w-7 flex-none text-data-sm", faint)}>
        {/* A null rank is a real state — the viewer has no XP this week, or has
            opted out. An invented "—" position would be a fabricated last
            place (UI spec §1.4). */}
        {row.rank === null ? "—" : row.rank}
      </span>
      <Monogram name={row.displayName} />
      <span className="min-w-0 flex-1 truncate text-body-md text-ink">
        {row.displayName}
        {isViewer ? (
          <span className={cn("ms-2 text-body-sm", faint)}>You</span>
        ) : null}
      </span>
      <StreakBadge streak={row.streak} />
      <span className="w-16 flex-none text-end text-data-md text-ink">
        {/* Only the viewer's own figure counts up — see this file's header on
            why the rest of the board holds still. */}
        {isViewer ? <CountUp value={row.xp} /> : row.xp.toLocaleString()}
        <span className={cn("ms-1 text-body-sm", faint)}>XP</span>
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
        marginalia="No school on your account yet"
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
          marginalia="A quiet week so far"
          heading={
            scope === "friends"
              ? "Nobody has earned XP yet this week"
              : "No XP earned here yet this week"
          }
          body="Correct a paper, review flashcards or finish a study session. The board fills as soon as anyone does."
        />
      ) : (
        <ol className="divide-y divide-rule">
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
        <div className="mt-2 border-t border-rule pt-2">
          <BoardRow row={board.viewer} isViewer />
          {board.viewerOptedOut ? (
            <p className="pt-1 text-body-sm text-ink-faint">
              Your XP is still counted and still yours to see. You are just
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
/*
 * This screen's own `useStudentProfile()` call below (for the subjects/basis
 * row) goes through `<QueryState>`; this one deliberately does not. `isError`
 * returning nothing here is not an omission `<QueryState>` would fix — it is
 * the specific, load-bearing decision the comment below explains ("no control
 * at all rather than a control defaulted to visible"), and `<QueryState>`'s
 * `error` slot always renders a visible `ErrorState`, which is exactly the
 * "guess and show something" this control must not do on a failed read of a
 * public-facing toggle.
 */
function OptOutControl() {
  const { data, isPending, isError } = useStudentProfile()
  const patch = usePatchStudentProfile()

  // No control at all rather than a control defaulted to "visible": guessing
  // wrong in that direction shows a student on a public board they may have
  // asked to leave. An *error* is therefore still nothing — but a *pending*
  // read is not, see below.
  if (isError) return null

  // `data` is undefined for exactly as long as the read is in flight, so this
  // is the pending test — `isPending` alone would leave the render below
  // dereferencing an undefined profile.
  const pending = isPending || !data
  const optedOut = data?.profile.leaderboardOptOut === true
  return (
    <div
      /* P6.7 — while the profile read is in flight this renders its own frame
         with the copy present but `invisible`, rather than returning null and
         then appearing. Returning null shifted every section below this one
         down by the block's full height the moment the read landed, and that
         was one of the two layout shifts Lighthouse recorded on this route
         (CLS 0.386, performance 74 < 80). Reserving the space with the real
         strings — not a fixed `min-h-*` — is what makes the reservation match
         at every breakpoint, because the height comes from the same text
         wrapping in the same box.
         `invisible` (visibility: hidden) and not `opacity-0`: the placeholder
         must not be reachable, and `aria-hidden` + `inert` keep it out of the
         accessibility tree and off the tab order while it holds the space.
         It states nothing about the student's setting, which is the property
         the note above actually protects. */
      aria-hidden={pending || undefined}
      inert={pending || undefined}
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-md border border-rule bg-paper-sunk px-3.5 py-3",
        pending && "invisible",
      )}
    >
      <div className="min-w-0">
        <p className="text-body-md text-ink">
          {optedOut ? "You are hidden from other students" : "You appear on public boards"}
        </p>
        <p className="text-body-sm text-ink-faint">
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
        disabled={patch.isPending || pending}
        className="flex-none"
      >
        {optedOut ? "Show me again" : "Hide me"}
      </Button>
      {/* The one mutation on this screen, and it changes who can see the
          student — so a failure has to be visible. Surface 3's headline was
          two destructive mutations whose `isError` nothing rendered, and this
          is the same shape: without it, a failed "Hide me" leaves the toggle
          reading the old value with no explanation, and the student reasonably
          concludes they are hidden when they are not. */}
      {patch.isError ? (
        <p role="alert" className="w-full text-body-sm text-err">
          Your visibility could not be changed, so it is still as it was. Check
          your connection and try again.
        </p>
      ) : null}
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
        // The press and hover physics C-1 `Button` already carries (§9.2:
        // `scale(0.98)` press, colour shift on hover, never `ease-in-out`).
        // These tabs are real buttons and had none of it — they were the only
        // controls on the screen that did not respond to being pressed.
        "rounded-md border px-3 py-1.5 text-label transition-colors duration-[var(--dur-instant)] ease-out-soft active:scale-[0.98]",
        active
          ? "border-accent bg-accent-wash text-accent-ink"
          : "border-rule bg-paper-raised text-ink-muted hover:bg-paper-sunk",
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

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <Eyebrow>Standings</Eyebrow>
        {/* `text-display` was the class here and it resolves to nothing — see
            the note in `Profile.tsx`. */}
        <h1 className="text-display-lg text-ink">Effort, not marks</h1>
        <p className="lm-prose text-body-lg text-ink-muted">
          Boards rank XP: the work you put in. Nobody here can see anyone's
          grades.
        </p>
      </header>

      <OptOutControl />

      <section className="flex flex-col gap-4" aria-labelledby="s29-board">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="s29-board" className="text-display-sm text-ink">
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

        {/* P6.7 — the same reservation as `OptOutControl`, for the same reason
            and one row smaller: this selector cannot be rendered until the
            profile names the student's subjects, and appearing from nothing
            pushed the whole board and the section under it down. A single
            `invisible` tab holds one row's height while the read is in
            flight. It collapses to nothing once we know there are no subjects,
            which is correct — that is an answer, not a wait. */}
        <QueryState
          query={profile}
          skeleton={
            <div className="flex flex-wrap gap-2" aria-hidden="true" inert>
              <TabButton active={false} onClick={() => {}}>
                <span className="invisible">All subjects</span>
              </TabButton>
            </div>
          }
          /*
           * NEW: a failed profile read used to fall through to `subjects = []`
           * with nothing said about it — indistinguishable on screen from a
           * student who genuinely has no declared subjects. `isEmpty` below
           * still renders nothing for that real, successful case (an empty
           * fragment, not `empty` left unset — see its own comment); this
           * `error` slot is what now tells the difference on a real failure.
           */
          error={{
            heading: "Couldn't load your subjects",
            body: studentLoadFailureMessage,
            // The slot this fills is a one-row tab strip above the leaderboard,
            // so the full centred panel would shove the board down the page and
            // read as though the whole screen had failed. It has not: the board
            // below still works. `compact` keeps the failure the size of the
            // thing that failed.
            compact: true,
          }}
          isEmpty={(data) => data.enrolments.length === 0}
          // Explicit empty fragment, not left unset: `QueryState` falls
          // through an unset `empty` to `children(data)`, which here would
          // render the "All subjects" tab alone with nothing beside it — the
          // pre-conversion code rendered nothing at all when there were no
          // subjects to pick between, and this keeps that.
          empty={<></>}
        >
          {(data) => {
            // The basis options are the student's own declared subjects, not
            // a global catalogue: a board for a subject they do not sit is
            // noise they cannot act on (D5.14 §4's reasoning applied to the
            // second selector).
            const subjects = data.enrolments.map((e) => e.subjectCode)
            return (
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
            )
          }}
        </QueryState>

        <Card>
          {/* P6.7 — a floor on the board's height, applied in every state
              rather than only while loading. The board is the largest
              variable-height block on the screen and it sat directly above
              `s29-subjects`, the element Lighthouse named in both recorded
              shifts: a one-line "Loading the board…" growing into a real board
              moved that section ~335px down the page. 384px is the height of
              the smallest *real* board state on seeded data (a C-11 empty
              panel plus the pinned viewer row), so the floor is a measurement
              of the content, not a number chosen to satisfy a metric.
              It also stops the page jumping when the student switches between
              the Friends/Class/School/Everyone tabs, which is the same defect
              seen by a person instead of by Lighthouse. */}
          <CardBody className="min-h-96">
            <QueryState
              query={board}
              /*
               * `useLeaderboard` disables itself when `scope === "class"` and
               * there is no class id (`enabled: !needsClass ||
               * Boolean(classId)` — see that hook), which parks it at
               * `pending`/`fetchStatus: "idle"` forever rather than fetching
               * and failing — the `idle` trap `query-state.tsx`'s own header
               * names. That state is reached in exactly two situations here,
               * which read differently to a student: `classes` (this
               * student's own class list, used to derive `effectiveClassId`
               * above) is still loading, in which case the board's own
               * skeleton is the honest thing to show — a decision is coming,
               * not "no class" — or `classes` has settled and genuinely came
               * back empty (or failed), which is the real "not in a class
               * yet" case this Card already carried before this conversion.
               */
              idle={
                classes.isPending ? (
                  <ListSkeleton rows={6} avatar className="border-0 bg-transparent" />
                ) : classes.isError ? (
                  // NEW: before this conversion a failed `classes` read
                  // collapsed into the same "not in a class yet" copy as a
                  // genuinely empty class list — a fetch failure and a real
                  // fact about the student's account read as one sentence.
                  // Distinguished here, with its own retry.
                  <ErrorState
                    heading="Couldn't load your classes"
                    body={studentLoadFailureMessage(classes.error)}
                    action={{ label: "Try again", onClick: () => void classes.refetch() }}
                  />
                ) : (
                  <EmptyState
                    marginalia="No class join code yet"
                    heading="You are not in a class yet"
                    body="Class boards rank you against your classmates. Ask your teacher for a join code, or try the friends board."
                  />
                )
              }
              skeleton={
                /* P4.4 — was a line of text where a ranked list arrives. The
                   `min-h-96` floor above already stopped the page from jumping,
                   but a floor only reserves the space; it does not tell the
                   reader what is coming. Six rows with a monogram is the board's
                   own geometry, and `border-0` because it is already inside the
                   card's frame. */
                <ListSkeleton rows={6} avatar className="border-0 bg-transparent" />
              }
              error={{
                heading: "The board could not be loaded",
                body: "This is a connection problem, not an empty board. Your classmates' XP is still there.",
              }}
            >
              {(data) => <BoardBody board={data} scope={scope} />}
            </QueryState>
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
        <h2 id="s29-subjects" className="text-display-sm text-ink">
          Your subjects
        </h2>
        <Card>
          <CardBody>
            <QueryState
              query={standings}
              skeleton={<ListSkeleton rows={3} className="border-0 bg-transparent" />}
              error={{
                heading: "Subject standings could not be loaded",
                body: "A connection problem. Nothing has changed about your subjects.",
              }}
              isEmpty={(data) => data.subjectRanks.length === 0}
              empty={
                <EmptyState
                  marginalia="Nothing marked yet"
                  heading="No subjects ranked yet"
                  body="Correct a paper and your subjects appear here."
                />
              }
            >
              {(data) => (
                /* P4.4 — the rank column had no label. A bare tone-coloured "3"
                   at the end of a row that already ends in "9 papers" is not
                   self-describing: the two adjacent figures invited being read
                   as a pair, and nothing said the second was a position. A
                   header row costs one line and answers it, and the per-row
                   `sr-only` gives the same answer to a screen reader, which
                   cannot see the column at all. */
                <div className="flex flex-col gap-2.5">
                  <div
                    aria-hidden="true"
                    className="flex items-center gap-3 border-b border-rule pb-1.5 text-eyebrow text-ink-faint"
                  >
                    <span className="w-11 flex-none">Code</span>
                    <span className="min-w-0 flex-1">Subject</span>
                    <span>Marked</span>
                    <span className="w-10 flex-none text-end">Rank</span>
                  </div>
                  {data.subjectRanks.map((s) => (
                    <div key={s.code} className="flex items-center gap-3">
                      <span className="w-11 flex-none text-data-sm text-ink-faint">
                        {s.code}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-body-md text-ink">
                        {s.name}
                      </span>
                      <span className="text-body-sm text-ink-faint">
                        {s.papers} papers
                      </span>
                      <span
                        className={`w-10 flex-none text-end text-data-md ${vizText(s.color)}`}
                      >
                        <span className="sr-only">Rank </span>
                        {s.rank}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </QueryState>
          </CardBody>
        </Card>
      </section>
    </div>
  )
}
