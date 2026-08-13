import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Flag, WifiSlash } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Meter } from "@/components/ui/primitives"
import { ErrorState } from "@/components/ui/state-views"
import { useSaveQuizAnswer, useStudentQuizTake, useSubmitQuiz } from "@/lib/hooks/usePlacementApi"
import type { StudentQuizQuestion, SubmitQuizResponse } from "@/lib/placementTypes"
import { ApiError } from "@/lib/api"
import {
  answerCacheKey,
  answerInputKind,
  buildRetrySavePayload,
  clampQuestionIndex,
  countUnanswered,
  dirtyQuestionRefs,
  formatDuration,
  formatQuestionTopic,
  isCacheEntryUnchanged,
  mergeAnswers,
  quizAffiliationLabel,
  readCachedAnswers,
  refsToFlush,
  refsToRetry,
  remainingSeconds,
  seedAnswers,
  writeCachedAnswers,
  type CachedAnswers,
  type LocalAnswer,
} from "./quizTakerData"

/*
 * QuizTaker — the first question-rendering + answer-input surface in the
 * product (P4.8 chunk B, S-04). Built as a reusable component under
 * `components/quiz/`, not a screen-local one-off: P4.9's practice quizzes
 * and P5's assigned-quiz taking compose the same `/api/student/quizzes/
 * {assignmentId}/...` routes this component already wraps — including the
 * teacher-assigned case, where `header.className`/`header.teacherName` are
 * real (placement's are always `null`, D4.6 §3; `quizAffiliationLabel`
 * renders the line only when at least one is present).
 *
 * Answer persistence (UI spec S-04: "connection lost mid-test — answers
 * must survive; resume after leaving"): every keystroke updates local
 * state immediately AND is mirrored into `localStorage` synchronously via
 * `writeCachedAnswers`, tagged `dirty: true` (so a hard reload before the
 * debounced save fires still has the in-progress text — `mergeAnswers` is
 * the pure function that decides a dirty local edit beats the server's
 * older value on reload). A debounced autosave then PUTs the question's
 * current cached state (`buildRetrySavePayload`, both fields — safe because
 * the cache always holds the question's true current state); on success the
 * cache entry flips to `dirty: false`, but only if it still holds what that
 * save actually sent (`isCacheEntryUnchanged`). Saves for one question are
 * serialized through `saveChains` so two can never race each other to the
 * server. A failed save is shown per-question, never swallowed, and
 * `dirtyQuestionRefs` drives a resend once the browser reports `online`
 * again — and again, blocking, before any submit.
 *
 * No maths renderer (measured: 1/273 stems are LaTeX-shaped, the rest is
 * plain Unicode browsers render natively) — `white-space: pre-line` on the
 * stem is what actually matters, since stems carry real newlines.
 */

type SaveStatus = "idle" | "saving" | "saved" | "error"

function storageKey(assignmentId: string, suffix: string): string {
  return `lm.quiz.${suffix}.${assignmentId}`
}

/** Read a JSON-encoded localStorage value, tolerating a missing/corrupt
 * entry (private browsing, a manually-edited value) by returning `null`
 * rather than throwing — this is a resume convenience, not a source of
 * truth, so a bad cache must never crash the take screen. Used for the two
 * scalar caches (`startedAt`, `flags`); the answer cache has its own typed
 * `readCachedAnswers`/`writeCachedAnswers` in `quizTakerData.ts`. */
function readCache<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeCache(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage full/unavailable (private mode). The in-memory state and the
    // debounced server save are still the primary paths; losing the local
    // mirror degrades resume-after-reload, not correctness.
  }
}

function clearCache(assignmentId: string): void {
  for (const suffix of ["answers", "startedAt", "flags"]) {
    try {
      window.localStorage.removeItem(storageKey(assignmentId, suffix))
    } catch {
      // best-effort
    }
  }
}

function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener("online", goOnline)
    window.addEventListener("offline", goOffline)
    return () => {
      window.removeEventListener("online", goOnline)
      window.removeEventListener("offline", goOffline)
    }
  }, [])
  return online
}

function useElapsedSeconds(assignmentId: string): number {
  const startedAtRef = useRef<number>(0)
  if (startedAtRef.current === 0) {
    const key = storageKey(assignmentId, "startedAt")
    const cached = readCache<number>(key)
    if (cached) {
      startedAtRef.current = cached
    } else {
      startedAtRef.current = Date.now()
      writeCache(key, startedAtRef.current)
    }
  }
  const [elapsed, setElapsed] = useState(() =>
    Math.floor((Date.now() - startedAtRef.current) / 1000),
  )
  useEffect(() => {
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 1000)
    return () => window.clearInterval(id)
  }, [])
  return elapsed
}

export interface QuizTakerProps {
  assignmentId: string
  onSubmitted: (result: SubmitQuizResponse) => void
  /** "Leave for now" — omit to hide the affordance (e.g. a required flow). */
  onExit?: () => void
  className?: string
}

export function QuizTaker({ assignmentId, onSubmitted, onExit, className }: QuizTakerProps) {
  const { data, isPending, isError, error } = useStudentQuizTake(assignmentId)
  const saveAnswer = useSaveQuizAnswer(assignmentId)
  const submitQuiz = useSubmitQuiz(assignmentId)
  const online = useOnlineStatus()
  const elapsedSeconds = useElapsedSeconds(assignmentId)

  const [answers, setAnswers] = useState<Record<string, LocalAnswer>>({})
  const [saveStatus, setSaveStatus] = useState<Record<string, SaveStatus>>({})
  const [flagged, setFlagged] = useState<Set<string>>(new Set())
  const [index, setIndex] = useState(0)
  const [confirmingSubmit, setConfirmingSubmit] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const seeded = useRef(false)
  const [seedVersion, setSeedVersion] = useState(0)
  const debounceTimers = useRef<Record<string, number>>({})
  // The single source of truth for "what's safe to resend" — every entry
  // here is written to `localStorage` too, so it survives a reload as well
  // as an in-session retry. `dirty: true` means "not yet confirmed saved".
  const answerCache = useRef<CachedAnswers>({})

  useEffect(() => {
    if (seeded.current || !data) return
    seeded.current = true
    const server = seedAnswers(data.questions)
    const cached = readCachedAnswers(window.localStorage, answerCacheKey(assignmentId))
    answerCache.current = cached ?? {}
    // `mergeAnswers` is the pin: a dirty (unsaved) cached edit beats the
    // server's older value; a clean one defers back to the server.
    setAnswers(mergeAnswers(server, cached))
    const cachedFlags = readCache<string[]>(storageKey(assignmentId, "flags"))
    if (cachedFlags) setFlagged(new Set(cachedFlags))
    setSeedVersion((v) => v + 1)
  }, [data, assignmentId])

  const questions = useMemo(() => data?.questions ?? [], [data])
  const current: StudentQuizQuestion | undefined = questions[index]

  const persistCacheEntry = useCallback(
    (questionRef: string, entry: LocalAnswer, dirty: boolean) => {
      answerCache.current = { ...answerCache.current, [questionRef]: { ...entry, dirty } }
      writeCachedAnswers(window.localStorage, answerCacheKey(assignmentId), answerCache.current)
    },
    [assignmentId],
  )

  // One promise chain per question ref, holding the tail of that question's
  // outstanding saves, and the set of refs that currently have one.
  //
  // Saves for a given question are serialized rather than allowed to
  // overlap. Two could previously be on the wire at once — the reconnect
  // retry resending the cached value, and a debounced edit sending a
  // just-typed newer one — and since network arrival order is not dispatch
  // order and the server's upsert is last-write-wins with no version guard,
  // the OLDER value could land last at the server and win. The completion
  // handler then wrote its own captured value back into the cache marked
  // clean, so the newer answer was lost locally too, silently, while it was
  // still on screen. See `isCacheEntryUnchanged` for the full write-up.
  //
  // Chaining keeps the property that made the debounce path skip the
  // in-flight check in the first place: a newer edit is never dropped as a
  // duplicate. It is queued, and because each run reads `answerCache` when
  // its turn comes rather than when it was queued, it sends the newest value
  // rather than the one that was current at queue time.
  const saveChains = useRef<Record<string, Promise<void>>>({})
  const busyRefs = useRef<Set<string>>(new Set())

  // `saveAnswer.mutateAsync` and NOT `saveAnswer`: react-query returns
  // `{ ...result, mutateAsync }` — a fresh object every render — while
  // `mutateAsync` itself is stable on the observer. Depending on the whole
  // result object made the save callback change identity on every render,
  // which made the retry effect below re-run on every render and resend
  // every dirty answer each time. With a 1s elapsed-time tick already
  // forcing a render a second, that was a duplicate PUT per dirty answer per
  // second on the ordinary typing path, not just after a reconnect.
  const saveMutateAsync = saveAnswer.mutateAsync

  /**
   * Queue a save for one question and return a promise that settles when it
   * (and anything already queued ahead of it) is done.
   *
   * Never rejects: a failed save surfaces as the per-question `error` status
   * and leaves the entry `dirty`, which is what the retry pass and the
   * pre-submit flush both key on. Callers therefore check the cache for what
   * happened, not this promise.
   */
  const enqueueSave = useCallback(
    (questionRef: string): Promise<void> => {
      const run = async (): Promise<void> => {
        const entry = answerCache.current[questionRef]
        // Nothing to do: either the question has no cache entry, or a save
        // queued ahead of this one already carried this value to the server.
        if (!entry || !entry.dirty) return
        const sent: LocalAnswer = { answerText: entry.answerText, workingText: entry.workingText }
        setSaveStatus((prev) => ({ ...prev, [questionRef]: "saving" }))
        try {
          await saveMutateAsync({ questionRef, body: buildRetrySavePayload(sent) })
        } catch {
          setSaveStatus((prev) => ({ ...prev, [questionRef]: "error" }))
          return
        }
        // Only mark clean if the cache still holds what we actually sent. If
        // the student typed while this was on the wire, the entry stays
        // dirty and the edit that changed it has its own save chained behind
        // this one.
        if (!isCacheEntryUnchanged(answerCache.current[questionRef], sent)) return
        persistCacheEntry(questionRef, sent, false)
        setSaveStatus((prev) => ({ ...prev, [questionRef]: "saved" }))
      }
      const previous = saveChains.current[questionRef] ?? Promise.resolve()
      // `run, run` — run next in the chain whether the previous link
      // resolved or rejected, so one failure cannot strand every later save
      // for that question.
      const chained: Promise<void> = previous.then(run, run).then(() => {
        // Only the tail clears the slot; an earlier link finishing while
        // another is queued behind it must leave the chain intact.
        if (saveChains.current[questionRef] === chained) {
          delete saveChains.current[questionRef]
          busyRefs.current.delete(questionRef)
        }
      })
      saveChains.current[questionRef] = chained
      busyRefs.current.add(questionRef)
      return chained
    },
    [saveMutateAsync, persistCacheEntry],
  )

  // Resend every question still marked dirty in the cache, once the
  // browser reports it's back online — a lost connection must not strand
  // an answer as permanently unsaved once the student is reachable again.
  // Uses the full-both-fields retry payload (the cache holds the question's
  // true current state, so this re-asserts reality rather than risking a
  // partial, order-dependent resend of only "the last field touched").
  // `seedVersion` is in the deps so this also fires once the seeding effect
  // above has actually run. That is the reload-recovery half: an edit that
  // failed to save before a reload is restored into the UI by `mergeAnswers`,
  // but it is still only on this device — without this it would sit dirty
  // until the student happened to touch that question again or the browser
  // happened to go offline and back. `data` is usually undefined on the
  // first mount (the take query is still loading), so an `online`-only dep
  // list would have missed the seed entirely.
  useEffect(() => {
    if (!online) return
    for (const questionRef of refsToRetry(answerCache.current, busyRefs.current)) {
      void enqueueSave(questionRef)
    }
  }, [online, enqueueSave, seedVersion])

  function updateAnswer(questionRef: string, field: "answerText" | "workingText", value: string) {
    const prevEntry = answers[questionRef] ?? { answerText: null, workingText: null }
    const nextEntry: LocalAnswer = { ...prevEntry, [field]: value }
    setAnswers((prev) => ({ ...prev, [questionRef]: nextEntry }))
    persistCacheEntry(questionRef, nextEntry, true)
    const timers = debounceTimers.current
    if (timers[questionRef]) window.clearTimeout(timers[questionRef])
    timers[questionRef] = window.setTimeout(() => {
      delete debounceTimers.current[questionRef]
      void enqueueSave(questionRef)
    }, 600)
  }

  function toggleFlag(questionRef: string) {
    setFlagged((prev) => {
      const next = new Set(prev)
      if (next.has(questionRef)) next.delete(questionRef)
      else next.add(questionRef)
      writeCache(storageKey(assignmentId, "flags"), [...next])
      return next
    })
  }

  const liveQuestions = questions.map((q) => answers[q.questionRef] ?? { answerText: q.answerText, workingText: q.workingText })
  const unansweredCount = countUnanswered(liveQuestions)

  /**
   * Push every still-unsaved answer to the server and wait for it, before
   * the quiz is submitted.
   *
   * Without this, two ordinary sequences silently lose a real answer. A
   * student who types and hits submit inside the 600ms debounce has that
   * edit sitting in a timer that `handleSubmit` never fires — the answer
   * exists only on this device while the paper is marked without it. And an
   * answer whose save failed while online has no other resend trigger before
   * submit (the retry effect fires on reconnect and on seed, neither of
   * which is a submit). Marking a paper against an answer the student can
   * see on screen but the marker never received is exactly the
   * confidently-wrong shape D3.21 flagged.
   *
   * A failure here therefore blocks the submit rather than being swallowed:
   * submitting anyway would mark a script that is not the one the student
   * wrote.
   *
   * The failure test is the cache, not the promises: `enqueueSave` never
   * rejects, and a save that failed leaves its entry `dirty`. Checking the
   * cache afterwards is the stronger contract anyway — it blocks on *any*
   * answer that is not confirmed saved, however it got that way, rather than
   * only on the ones this call happened to put on the wire.
   */
  async function flushPendingSaves(): Promise<void> {
    // Cancel the debounce timers first, so nothing dispatches a save behind
    // the flush's back after it has read the cache.
    const timers = debounceTimers.current
    for (const questionRef of Object.keys(timers)) {
      window.clearTimeout(timers[questionRef])
      delete timers[questionRef]
    }
    await Promise.all(
      refsToFlush(answerCache.current, busyRefs.current).map((questionRef) =>
        enqueueSave(questionRef),
      ),
    )
    const unsaved = dirtyQuestionRefs(answerCache.current)
    if (unsaved.length > 0) {
      throw new Error(`${unsaved.length} answer(s) are not saved`)
    }
  }

  async function handleSubmit() {
    setSubmitError(null)
    try {
      await flushPendingSaves()
    } catch {
      setSubmitError(
        "We couldn't save your latest answers, so we haven't submitted yet. Check your connection and try again. Nothing you've written has been lost.",
      )
      setConfirmingSubmit(false)
      return
    }
    try {
      const result = await submitQuiz.mutateAsync()
      clearCache(assignmentId)
      onSubmitted(result)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "We couldn't submit that. Try again.")
      setConfirmingSubmit(false)
    }
  }

  function requestSubmit() {
    if (unansweredCount > 0) {
      setConfirmingSubmit(true)
    } else {
      void handleSubmit()
    }
  }

  /* Every branch below carries an `sr-only` h1 rather than a visible one,
   * because this screen deliberately has no visible page title: the identity
   * a student needs mid-test is "Question 3 of 10" and the countdown, and a
   * banner title would push both down the viewport on a 380px phone. The
   * heading still has to exist — QUALITY-BAR.md requires one h1 per page, and
   * a screen reader otherwise lands on this screen with nothing to orient by.
   * P3's ReviewItem/QuizBuilder set the same precedent. */
  if (isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Test in progress</h1>
        Loading your test…
      </div>
    )
  }

  if (isError || !data) {
    const message =
      error instanceof ApiError && error.status === 403
        ? "This test isn't yours to take."
        : error instanceof ApiError && error.status === 404
          ? "This test couldn't be found."
          : error?.message ?? "Couldn't load this test."
    return (
      <>
        <h1 className="sr-only">Test in progress</h1>
        <ErrorState heading="Couldn't load your test" body={message} className="lm-screen" />
      </>
    )
  }

  if (!current) {
    return (
      <>
        <h1 className="sr-only">Test in progress</h1>
        <ErrorState heading="This test has no questions" className="lm-screen" />
      </>
    )
  }

  const total = questions.length
  const remaining = remainingSeconds(data.header.timeLimitMinutes, elapsedSeconds)
  const timeNearlyUp = remaining !== null && remaining <= 120
  const kind = answerInputKind(current.questionType, current.mcqOptions)
  const currentAnswer = answers[current.questionRef] ?? { answerText: current.answerText, workingText: current.workingText }
  const currentStatus = saveStatus[current.questionRef] ?? "idle"
  const currentFlagged = flagged.has(current.questionRef)
  const affiliation = quizAffiliationLabel(data.header.className, data.header.teacherName)

  return (
    <div className={cn("lm-screen mx-auto flex max-w-[820px] flex-col gap-5", className)}>
      {/* The real title, not a generic one — this component is composed by
       * placement now and by practice/assigned quizzes in P4.9/P5, so the
       * heading names whichever test the student is actually sitting. */}
      <h1 className="sr-only">{data.header.quizTitle}</h1>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-0.5">
          <div className="text-dense-sm text-t2">
            Question {index + 1} of {total}
          </div>
          {/* `null` for every placement test (no class, no teacher, D4.6 §3);
           * populated for a teacher-assigned quiz composing this same
           * component in P4.9/P5. Never a "—" placeholder for the absent
           * case — nothing renders here at all. */}
          {affiliation ? <div className="text-3xs text-t3">{affiliation}</div> : null}
        </div>
        <div className="flex-1" />
        {!online ? (
          <Chip tone="warn" className="gap-1">
            <WifiSlash size={12} weight="bold" aria-hidden />
            Offline. Answers save locally.
          </Chip>
        ) : null}
        <Chip tone={timeNearlyUp ? "warn" : "neutral"} className="font-mono">
          {remaining !== null ? `${formatDuration(remaining)} left` : `${formatDuration(elapsedSeconds)} elapsed`}
        </Chip>
        {/* `min-h-[44px]` below: see the SubjectsStep note — `size="sm"` is
         * ~31px and this is a phone-primary screen. */}
        {onExit ? (
          <Button variant="ghost" size="sm" className="min-h-[44px]" onClick={onExit}>
            Leave for now
          </Button>
        ) : null}
      </div>

      <Meter
        value={((index + 1) / total) * 100}
        label={`Question ${index + 1} of ${total}`}
        className="h-1.5"
      />

      {timeNearlyUp ? (
        <div className="rounded-lg border border-warn bg-warn-bg px-4 py-2.5 text-dense-sm text-warn">
          Less than 2 minutes left.
        </div>
      ) : null}

      <Card>
        <CardBody className="flex flex-col gap-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="neutral" className="font-mono">
                {current.totalMarks} mark{current.totalMarks === 1 ? "" : "s"}
              </Chip>
              <Chip tone={current.topic ? "accent" : "neutral"}>
                {formatQuestionTopic(current.topic)}
              </Chip>
            </div>
            <button
              type="button"
              onClick={() => toggleFlag(current.questionRef)}
              aria-pressed={currentFlagged}
              className={cn(
                // `min-h-[44px]` per QUALITY-BAR.md:40, the same idiom the rest
                // of the library uses. This is a phone-primary control used
                // mid-exam — "come back to this question" — so a missed tap
                // costs the student the question. Padding alone left it ~30px:
                // tall enough for WCAG 2.5.8 AA (24px), which is exactly why no
                // automated gate flagged it.
                "flex min-h-[44px] items-center gap-1.5 rounded px-2.5 py-1.5 text-dense-sm transition-colors cursor-pointer",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                currentFlagged ? "bg-warn-bg text-warn" : "text-t3 hover:bg-surface-2",
              )}
            >
              <Flag weight={currentFlagged ? "fill" : "regular"} size={14} aria-hidden />
              {currentFlagged ? "Flagged for review" : "Flag for review"}
            </button>
          </div>

          <p className="whitespace-pre-line text-body-lg leading-relaxed text-t1">
            {current.prompt}
          </p>

          <AnswerInput
            kind={kind}
            question={current}
            value={currentAnswer}
            onAnswerText={(v) => updateAnswer(current.questionRef, "answerText", v)}
            onWorkingText={(v) => updateAnswer(current.questionRef, "workingText", v)}
          />

          <SaveIndicator status={currentStatus} online={online} />
        </CardBody>
      </Card>

      {confirmingSubmit ? (
        <Card className="border-warn">
          <CardBody className="flex flex-col gap-3">
            <div className="text-body-md font-medium text-t1">
              You have {unansweredCount} unanswered question{unansweredCount === 1 ? "" : "s"}.
            </div>
            <p className="text-dense-sm text-t2">
              You can still go back and answer them, or submit as-is.
            </p>
            {submitError ? <p className="text-dense-sm text-err">{submitError}</p> : null}
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => setConfirmingSubmit(false)}>
                Go back
              </Button>
              <Button variant="accent" disabled={submitQuiz.isPending} onClick={() => void handleSubmit()}>
                {submitQuiz.isPending ? "Submitting…" : "Submit anyway"}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            disabled={index === 0}
            onClick={() => setIndex((i) => clampQuestionIndex(i - 1, total))}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            disabled={index === total - 1}
            onClick={() => setIndex((i) => clampQuestionIndex(i + 1, total))}
          >
            Next
          </Button>
          <div className="flex-1" />
          {submitError ? <p className="text-dense-sm text-err">{submitError}</p> : null}
          <Button variant="accent" disabled={submitQuiz.isPending} onClick={requestSubmit}>
            {submitQuiz.isPending ? "Submitting…" : "Submit test"}
          </Button>
        </div>
      )}
    </div>
  )
}

function SaveIndicator({ status, online }: { status: SaveStatus; online: boolean }) {
  if (status === "idle") return null
  if (status === "error") {
    return (
      <p className="text-dense-sm text-err" role="status">
        {online
          ? "We couldn't save this answer. It's kept on this device, and we'll send it again before you submit."
          : "Offline. This will save once you're back online."}
      </p>
    )
  }
  if (status === "saving") {
    return (
      <p className="text-dense-sm text-t3" role="status">
        Saving…
      </p>
    )
  }
  return (
    <p className="text-dense-sm text-t3" role="status">
      Saved
    </p>
  )
}

function AnswerInput({
  kind,
  question,
  value,
  onAnswerText,
  onWorkingText,
}: {
  kind: ReturnType<typeof answerInputKind>
  question: StudentQuizQuestion
  value: LocalAnswer
  onAnswerText: (v: string) => void
  onWorkingText: (v: string) => void
}) {
  if (kind === "mcq") {
    return (
      <div className="flex flex-col gap-2" role="radiogroup" aria-label="Choose an answer">
        {(question.mcqOptions ?? []).map((option) => {
          const selected = value.answerText === option
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onAnswerText(option)}
              className={cn(
                "flex items-center gap-3 rounded-lg border px-4 py-3 text-left text-body-md cursor-pointer transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                selected
                  ? "border-accent bg-accent-subtle text-accent-subtle-on"
                  : "border-border bg-surface text-t1 hover:bg-surface-2",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "flex h-4 w-4 flex-none items-center justify-center rounded-full border",
                  selected ? "border-accent bg-accent" : "border-border",
                )}
              />
              {option}
            </button>
          )
        })}
      </div>
    )
  }

  if (kind === "short") {
    return (
      <input
        type="text"
        value={value.answerText ?? ""}
        onChange={(event) => onAnswerText(event.target.value)}
        placeholder="Your answer"
        className="min-h-[44px] rounded-lg border border-border bg-surface px-4 py-3 text-body-lg text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <label className="text-dense-sm text-t2" htmlFor={`working-${question.id}`}>
          Work it out on paper, then type your working here (optional)
        </label>
        <textarea
          id={`working-${question.id}`}
          value={value.workingText ?? ""}
          onChange={(event) => onWorkingText(event.target.value)}
          rows={4}
          placeholder="Show your working…"
          className="rounded-lg border border-border bg-surface px-4 py-3 text-body-md text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-dense-sm text-t2" htmlFor={`answer-${question.id}`}>
          Your answer
        </label>
        <textarea
          id={`answer-${question.id}`}
          value={value.answerText ?? ""}
          onChange={(event) => onAnswerText(event.target.value)}
          rows={3}
          placeholder="Your final answer"
          className="rounded-lg border border-border bg-surface px-4 py-3 text-body-md text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
      </div>
    </div>
  )
}
