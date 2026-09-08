/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowClockwise, Camera, UploadSimple } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { FileDrop } from "@/components/ui/file-drop"
import {
  ProcessingState,
  type ProcessingStage,
} from "@/components/ui/processing-state"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { CameraCapture } from "@/components/CameraCapture"
import {
  advanceStage,
  annotateActiveStage,
  failActiveStage,
  frameProgress,
} from "@/lib/pipelineStages"
import {
  canRetryInPlace,
  correctionFailureMessage,
  STREAM_ENDED_WITHOUT_RESULT,
} from "@/lib/correctionOutcome"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import {
  runCorrection,
  uploadScan,
  useActiveUpload,
  useUploadRun,
} from "@/lib/hooks/useStudentApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { canStartRun, runPhase } from "@/lib/uploadRun"
import { cn } from "@/lib/utils"
import { uploadStageProgress } from "@/lib/uploadProgress"
import type { QuestionResult, Result, StudentCorrectFrame, UploadRun } from "@/lib/studentTypes"
import { reassure } from "../data"

/** Which source the student is using to produce `scanFile`. */
type ScanSource = "file" | "camera"

/*
 * Correct a paper (isCorrect). Real upload + SSE flow: pick a scan (required)
 * and an optional mark scheme, upload both via `uploadScan`, then drive the
 * progress panel off `runCorrection`'s live frames. On the terminal
 * `phase: "complete"` frame, assembles a `Result & { questions }` object from
 * the frame's fields and navigates to the result screen with it as
 * `location.state` — `PaperResult` renders straight from that, no second GET.
 *
 * The marking-in-progress panel (S-14) renders via `ProcessingState` (C-10):
 * three discrete, independently-stated stages built from the SSE frame types
 * the backend actually emits (`extraction_progress`, `mark_scheme_progress`,
 * `marking_progress`) — never a single animated bar standing in for the whole
 * pipeline. See the stage-mapping note below for the two spec stages
 * (identifying the paper / analysing weak topics) this honestly omits because
 * no SSE frame exists for either yet.
 *
 * The state machine driving those stages (advance, back-fill, annotate, fail,
 * and read a frame's real counter) lives in `lib/pipelineStages.ts`, shared
 * with the teacher grading console so the two portals cannot describe the same
 * pipeline differently. What stays here is only what is genuinely
 * screen-specific: the stage list, the frame→stage mapping, and the wording.
 *
 * ── P4.2 (redesign Phase 4, surface 2 of 10) ──────────────────────────────
 *
 * Migrated to the Study Notebook system, and four things changed that are not
 * styling:
 *
 *   1. **Retry in place after a failure** (audit M5). The only way forward
 *      from a failed run was to pick the file again and re-upload it, which
 *      re-does the one part of the run that had already succeeded. `paperId`
 *      is now held past the failure, so "Start marking again" re-opens the
 *      stream against the scan the server already has. Re-uploading remains
 *      available by simply choosing a different file.
 *   2. **A run could end with no result and no error.** See
 *      `lib/correctionOutcome.ts` — `streamActivity` yielded nothing for a
 *      non-OK response, so a 500 read on screen as "Ready when you are".
 *      `api.ts` now throws, and a stream that closes without a terminal frame
 *      is treated here as the failure it is.
 *   3. **The server's words are no longer rendered verbatim.** The failure
 *      path printed `err.message`, so a dropped connection showed the
 *      browser's "Failed to fetch". A FastAPI `detail` written for a human is
 *      still shown, because it is the specific thing this screen cannot say
 *      better.
 *   4. **The page can now do what its own copy promised.** "Scan or drop the
 *      paper" has been the first sentence on this screen since the build era
 *      and there was no drop target anywhere on it. `FileDrop` (C-21) is one.
 *
 * **Deliberately NOT done here: audit M4** — the marking run lives in
 * component state, so a refresh mid-run loses it. That is Phase 6.2's, and it
 * is not a styling job: the teacher console hit the identical defect and the
 * fix was architectural (D6.13 — marking became a server-side job the console
 * polls, precisely so a reload could not wipe the only progress readout). The
 * student side still drives its run from the browser stream. Pulling that
 * forward would be a backend change smuggled into a design pass. What is done
 * here is the half of it that is honest to do now: the failure has a way out.
 *
 * ── P6.2 (redesign Phase 6, harden) ───────────────────────────────────────
 *
 * M4 is now closed, and the finding underneath it was not in this file.
 *
 * The run was never actually lost on a reload. `POST /student/correct` does its
 * work on a background thread that does not stop when the client disconnects,
 * and it persists the attempt when it finishes — so a student who reloaded had
 * a paper that would be marked, with nothing on screen that knew it. What was
 * missing was the record that a run was *in flight*: `UploadStatus.processing`
 * existed from the first migration and **no code path had ever written it**, so
 * a paper being marked right now was indistinguishable in the database from a
 * scan somebody uploaded and abandoned.
 *
 * With that written, recovery is a read. On mount this screen asks
 * `/student/uploads/active` whether the student has a run going and, if so,
 * follows it to a terminal status.
 *
 * Two things it deliberately does NOT do:
 *
 *   1. **It does not redraw the stage panel.** The SSE frames go to a
 *      process-global bus with no replay, so a recovered screen knows the run
 *      is going and nothing else. Ticking the three stages off again would be
 *      inventing progress, which is the one thing S-14 rules out by name.
 *   2. **It does not re-POST `/correct`.** That would start a *second* marking
 *      run over the same scan: Gemini paid for twice, a second attempt row,
 *      and two runs interleaving on one stream. The bus is per-run scoped now
 *      (DS10), but both runs would carry the *same* scope — they are the same
 *      paper — so scoping does not separate them the way it separates two
 *      different papers. Recovery polls; it never re-runs.
 *
 * A recovered run also unlocks the retry that could not work before: after a
 * reload there is no `File` object any more, but the server still has the scan,
 * so `canRetryInPlace` is the real test of whether marking can start, and the
 * local file is not required for it.
 *
 * ── PR 4 (loading-and-error-screens programme) ────────────────────────────
 *
 * Two things fixed here, both logged during PR 3's review and deferred to
 * this one.
 *
 * 1. **The upload had nothing on screen moving.** `uploadScan` posted through
 *    `fetch`, which cannot report upload progress, so the slowest part of this
 *    flow — a phone photo, on a bad connection — sat under "Marking…" with
 *    all three SSE-driven stages still pending, because none of them starts
 *    until the file has already landed. `uploadScan` now takes an
 *    `onProgress` callback (`lib/api.ts::uploadWithProgress`, `XMLHttpRequest`-
 *    based specifically because `fetch` cannot do this) and a fourth stage,
 *    `upload`, is prepended to `STAGE_ORDER` and driven from real
 *    `xhr.upload.onprogress` bytes via `resolvePaperId` below — not from a
 *    frame, because there is no SSE stream yet at this point in the flow.
 *    A resumed run (`canRetryInPlace`) has no bytes to report — they moved
 *    before this render existed — so that path marks `upload` done at once
 *    instead of leaving it at a 0% that will never move.
 * 2. **A failed `/student/uploads/active` check was invisible.** `active.data`
 *    stayed `undefined` forever, `strandedId` was never set, and a genuinely
 *    stranded run was never surfaced — no error, no retry, nothing. A compact
 *    `ErrorState` now renders alongside the ordinary panel when `active`
 *    errors, with its own retry; it does not replace the upload form, because
 *    the reader must still be able to start a fresh upload while the check
 *    for an old one is failing.
 */

/**
 * Four stages. The first, `upload`, is unlike the other three: it isn't
 * announced by an SSE frame at all, because it runs *before* the SSE stream
 * exists — the file has to land on the server before `/student/correct` can
 * open one. It is driven directly from `resolvePaperId`'s own
 * `uploadScan(..., { onProgress })` call below, off real `xhr.upload.
 * onprogress` bytes, using the same `advanceStage`/`failActiveStage` shared
 * with `streamCorrection`'s frame loop so both halves of this one pipeline
 * are described by the same machinery.
 *
 * `extract`, `scheme` and `mark` are the three stages the backend's SSE
 * frames give us real signal for. Spec S-14 also lists "identifying the
 * paper" and "analysing your weak topics" — omitted here because no frame
 * type announces the start/end of either; a stage with no event that could
 * ever move it out of "pending" would look stuck rather than honest.
 * Flagged in the P2.5.3 report as a content gap.
 */
const STAGE_ORDER = ["upload", "extract", "scheme", "mark"] as const
type StageId = (typeof STAGE_ORDER)[number]

const initialStages: ProcessingStage[] = [
  { id: "upload", label: "Uploading your scan", status: "pending" },
  { id: "extract", label: "Reading your answers", status: "pending" },
  { id: "scheme", label: "Fetching the mark scheme", status: "pending" },
  { id: "mark", label: "Marking your questions", status: "pending" },
]

/** Human label for one SSE frame, used as the active stage's detail text. */
function describeFrame(frame: StudentCorrectFrame): string {
  switch (frame.type) {
    case "mark_scheme_progress":
      return frame.message ?? "Resolving the mark scheme"
    case "extraction_progress":
      return frame.message ?? "Reading your answers"
    case "marking_progress":
      if (frame.phase === "complete") {
        // Middle dot, not a spaced hyphen: this is a separator between a word
        // and a figure, not punctuation, and the copy gate's classifier reads
        // a spaced hyphen as a dash (audit N1).
        return `Marked · ${frame.awarded ?? "?"}/${frame.max_marks ?? "?"}`
      }
      return frame.question_id ? `Marked question ${frame.question_id}` : "Marking"
    case "gemini_call_start":
      return "Calling the marking model"
    case "gemini_call_end":
      return "Model call finished"
    case "gemini_cache_hit":
      return "Reused a cached model call"
    case "gemini_retry":
      return "Retrying the model call"
    case "gemini_escalate":
      return "Escalating to a stronger model"
    case "budget_warning":
      return frame.message ?? "Approaching the marking budget"
    case "budget_exceeded":
      return frame.message ?? "Marking budget exceeded"
    default:
      return frame.message ?? frame.type
  }
}

/** Which stage (if any) a frame type reports real progress for. */
function frameStageId(frame: StudentCorrectFrame): StageId | null {
  if (frame.type === "extraction_progress") return "extract"
  if (frame.type === "mark_scheme_progress") return "scheme"
  if (frame.type === "marking_progress") return "mark"
  return null
}

/**
 * The scan-source toggle. A two-button group rather than a `Tabs`, because
 * these do not reveal two views of the same content: choosing one discards
 * whatever the other produced, which is a choice, not navigation.
 */
function SourceToggle({
  source,
  onChoose,
  disabled,
}: {
  source: ScanSource
  onChoose: (source: ScanSource) => void
  disabled: boolean
}) {
  const options: { id: ScanSource; label: string; icon: typeof UploadSimple }[] = [
    { id: "file", label: "Upload a file", icon: UploadSimple },
    { id: "camera", label: "Scan with camera", icon: Camera },
  ]
  return (
    <div
      role="group"
      aria-label="Scan source"
      className="inline-flex rounded-md border border-rule bg-paper-sunk p-0.5"
    >
      {options.map((option) => {
        const Glyph = option.icon
        const active = source === option.id
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChoose(option.id)}
            disabled={disabled}
            aria-pressed={active}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-sm px-3 py-1.5 text-label",
              "transition-colors duration-[var(--dur-instant)] ease-out-soft",
              "disabled:cursor-not-allowed disabled:opacity-50",
              active
                ? "bg-paper-raised text-ink"
                : "text-ink-muted hover:text-ink",
            )}
          >
            <Glyph size={16} aria-hidden="true" />
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * The "a run this tab is not streaming" prose panel — a recovered run (mid-
 * flight or stopped) that this tab did not itself drive. Reads its own phase
 * from `run` rather than trusting a caller's already-computed one, so the
 * transitional render (see `CorrectPaper`'s `skeleton` below, which passes
 * `active.data` before `stranded`'s own poll has answered) and the settled
 * one agree by construction rather than by two call sites staying in sync.
 *
 * Renders as prose and NOT as the stage list, because the stage list is a
 * claim about which step the pipeline reached and this reader has no such
 * information: the SSE frames went to a bus with no replay, and the tab that
 * was reading them is gone. Ticking stages off from a status word would be
 * the invented progress S-14 rules out.
 */
function StrandedRunPanel({ run, onRetry }: { run: UploadRun; onRetry: () => void }) {
  const phase = runPhase(run)
  const waiting = phase === "waiting"
  const stopped = phase === "stopped"
  return (
    <div className="flex flex-col gap-3">
      <p className="text-pretty text-body-sm text-ink-muted">
        {waiting
          ? "This paper was already being marked when you opened this page, and it is still going. Marking carries on even if you close the tab, so you can leave this open or come back later."
          : "This paper was being marked and the run stopped before it finished. Nothing was marked, and your scan is still here."}
      </p>
      {run.filename ? (
        <p className="text-body-sm text-ink">
          <span className="text-ink-muted">Paper</span>{" "}
          <span className="break-words">{run.filename}</span>
        </p>
      ) : null}
      {stopped ? (
        <Button
          variant="primary"
          size="sm"
          icon={<ArrowClockwise size={16} />}
          onClick={onRetry}
          className="self-start"
        >
          Start marking again
        </Button>
      ) : null}
    </div>
  )
}

export function CorrectPaper() {
  const navigate = useNavigate()
  const [scanFile, setScanFile] = useState<File | null>(null)
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<ProcessingStage[]>(initialStages)
  const [error, setError] = useState<string | null>(null)
  const [scanSource, setScanSource] = useState<ScanSource>("file")
  const [cameraSessionKey, setCameraSessionKey] = useState(0)
  /*
   * The uploaded paper, held past a failure so the run can be retried without
   * re-uploading (M5). Cleared whenever the *scan* changes, because the
   * identifier then refers to a file the student is no longer looking at, and
   * a retry that silently marks the previous scan is worse than no retry.
   */
  const [paperId, setPaperId] = useState<string | null>(null)

  /*
   * A run that was already going when this screen loaded — the reload case
   * (M4). A run THIS tab is streaming is not one of these: `running` is true
   * for the whole of that, and the id is already in `paperId`.
   */
  const active = useActiveUpload()
  const strandedId =
    !running && active.data && active.data.paperId !== paperId ? active.data.paperId : undefined
  const stranded = useUploadRun(strandedId)
  /*
   * Gated on `strandedId`, not on `stranded.data`. A disabled react-query keeps
   * its last value, so reading `stranded.data` directly would leave a finished
   * run on screen after this tab started its own — the recovered panel would
   * outlive the thing it recovered.
   */
  const strandedRun = strandedId ? (stranded.data ?? active.data) : null
  /*
   * The four statuses collapse to what the screen actually asks. `stale` is the
   * server's judgement that a `processing` row is one nobody will finish; it
   * owns that call because it owns the clock the timestamp came from.
   */
  const phase = runPhase(strandedRun)
  const waitingOnServer = phase === "waiting"
  const strandedStopped = phase === "stopped"

  /*
   * A recovered run that finished while the student watched goes to the result,
   * exactly as the streamed one does — but WITHOUT the `live` state, so the
   * result screen does not play its reveal. `PaperResult` reveals a figure that
   * arrived while this reader was watching it; a paper marked in another tab,
   * or before the reload, is not that, and animating it would be a flourish
   * over an observation the student never made.
   */
  useEffect(() => {
    if (phase === "done" && strandedRun) {
      navigate(`/student/result/${strandedRun.paperId}`)
    }
  }, [phase, strandedRun, navigate])

  /**
   * Every path that changes the scan goes through here, so `paperId` can never
   * outlive the file it identifies. A retry against a stale id would re-mark
   * the previous scan while the screen showed the new one.
   */
  const chooseScan = (file: File | null) => {
    setScanFile(file)
    setPaperId(null)
    setError(null)
    setStages(initialStages)
  }

  const chooseScanSource = (source: ScanSource) => {
    if (source === scanSource) return
    setScanSource(source)
    chooseScan(null)
    if (source === "camera") setCameraSessionKey((k) => k + 1)
  }

  /**
   * Drive the stream for an already-uploaded paper. Split from `runPipeline`
   * so the retry path and the first-run path are literally the same code:
   * a retry that took a different route through the pipeline would be a second
   * implementation of the flagship flow, free to drift from the first.
   */
  const streamCorrection = async (id: string) => {
    for await (const frame of runCorrection(id)) {
      if (frame.type === "warning" || frame.type === "error") {
        const message =
          frame.message ?? "The marking pipeline stopped and didn't report a reason."
        setStages((prev) => failActiveStage(prev, message))
        setError(message)
        return
      }
      const stageId = frameStageId(frame)
      const isComplete = frame.type === "marking_progress" && frame.phase === "complete"
      if (stageId) {
        // `frameProgress` is the whole per-question counter S-14 asks for
        // ("Question 7 of 21"): it returns a counter only when this frame
        // actually carried `index` + `total`, and undefined otherwise — so
        // frames without one (notably the terminal `phase: "complete"`
        // summary) leave the last real counter alone rather than inventing
        // or blanking a number.
        setStages((prev) =>
          advanceStage(
            prev,
            STAGE_ORDER,
            stageId,
            describeFrame(frame),
            isComplete,
            frameProgress(frame),
          ),
        )
      } else {
        setStages((prev) => annotateActiveStage(prev, describeFrame(frame)))
      }
      if (isComplete) {
        const assembled: Result & { questions: QuestionResult[] } = {
          code: frame.code ?? "",
          paper: frame.paper ?? "",
          session: frame.session ?? "",
          markerLabel: "",
          headline: "",
          summary: "",
          awarded: frame.awarded ?? 0,
          max: frame.max_marks ?? 0,
          pct: frame.pct ?? 0,
          grade: frame.grade ?? "",
          boundaryYear: frame.boundary_year ?? "",
          railLeft: frame.rail_left ?? 0,
          railFoot: frame.rail_foot ?? "",
          railNote: "",
          theory: [],
          integrity: [],
          provenance: "",
          questions: frame.questions ?? [],
        }
        navigate(`/student/result/${id}`, { state: assembled })
        return
      }
    }

    // Falling out of the loop means the stream closed without ever saying the
    // paper was marked and without an error frame. That used to end here
    // silently, leaving two ticks, a half-drawn third stage, and a panel
    // reading "Ready when you are".
    setStages((prev) => failActiveStage(prev, STREAM_ENDED_WITHOUT_RESULT))
    setError(STREAM_ENDED_WITHOUT_RESULT)
  }

  /*
   * The paper marking could start from right now, which is not the same as "the
   * paper in the form". After a reload the `File` is gone but the scan is still
   * on the server, so a run that stopped is restartable with nothing picked.
   */
  const resumableId = paperId ?? (strandedStopped ? (strandedRun?.paperId ?? null) : null)

  /**
   * The id to mark, uploading first only when the server has nothing yet.
   *
   * M5's retry lives here: `uploadScan` and `runCorrection` are two calls, and
   * when only the second failed, re-sending the multipart body would upload a
   * scan the server already has. Returns `null` when there is neither a file to
   * send nor a paper to re-mark, which is the one case the caller must not
   * start a run for.
   *
   * PR 4: this is also where the `upload` stage lives. `runPipeline` resets
   * every stage to `initialStages` (all pending) before calling this, so
   * whichever branch runs below has to give `upload` a real status of its
   * own rather than leaving it pending — a pending stage that nothing will
   * ever move looks stuck, which `failActiveStage`'s own "nothing had
   * started yet" case (see `pipelineStages.ts`) already treats as a place a
   * failure can land, and an *unstarted*-forever stage is the success-path
   * version of that same trap.
   */
  const resolvePaperId = async (): Promise<string | null> => {
    if (canRetryInPlace(resumableId)) {
      // Nothing to report: this is either a same-tab retry after the scan
      // already landed (M5) or a stopped run recovered from another tab
      // (P6.2). Either way the bytes moved before this render existed, so
      // the honest reading is "already done" — a bar stuck at a dead 0%
      // would claim a transfer is in flight that finished or never happened
      // in this tab at all.
      setStages((prev) => advanceStage(prev, STAGE_ORDER, "upload", undefined, true))
      return resumableId
    }
    if (!scanFile) return null
    setStages((prev) => advanceStage(prev, STAGE_ORDER, "upload", undefined, false))
    const uploaded = await uploadScan(scanFile, schemeFile ?? undefined, {
      onProgress: (progress) => {
        setStages((prev) =>
          advanceStage(prev, STAGE_ORDER, "upload", undefined, false, uploadStageProgress(progress)),
        )
      },
    })
    setStages((prev) => advanceStage(prev, STAGE_ORDER, "upload", undefined, true))
    return uploaded.paperId
  }

  const runPipeline = async () => {
    // A local file OR a scan the server already holds. Requiring the file was
    // what made a reloaded failure a dead end: after a reload the `File` is
    // gone, and the scan is not.
    if (running || (!scanFile && !canRetryInPlace(resumableId))) return
    setRunning(true)
    setError(null)
    setStages(initialStages)
    try {
      const id = await resolvePaperId()
      if (id === null) return
      setPaperId(id)
      await streamCorrection(id)
    } catch (err) {
      // A cancelled upload is not a failed one. `uploadWithProgress` rejects
      // with a `DOMException` named `AbortError` (matching what an aborted
      // `fetch` does), and that is an `Error` with a message, so without this
      // guard `correctionFailureMessage` would fall through to its "any Error
      // with a message" branch and print "Upload cancelled" as the reason a
      // red cross now sits on "Uploading your scan", under a panel headed
      // "Marking stopped". Nothing wires an `AbortSignal` through yet — see
      // `uploadScan`'s `signal` option — so this is unreachable today and is
      // here so that whoever adds the cancel control cannot land that bug.
      if (err instanceof DOMException && err.name === "AbortError") {
        setStages(initialStages)
        return
      }
      const message = correctionFailureMessage(err)
      setStages((prev) => failActiveStage(prev, message))
      setError(message)
    } finally {
      setRunning(false)
    }
  }

  const retryable = canRetryInPlace(resumableId)
  const primaryLabel = running || waitingOnServer ? "Marking…" : "Mark this paper"
  const retryLabel = retryable ? "Start marking again" : "Try again"
  /*
   * Nothing may start a second run while one is in flight. Two runs over one
   * scan would pay Gemini twice, write a second attempt row, and interleave
   * on one stream — per-run bus scoping (DS10) does not help here, because
   * both runs scope to the same paper. The form goes read-only rather than
   * disappearing, so the student can still see what is being marked.
   */
  /*
   * D7.5's gate, read before the run rather than after the refusal.
   * `undefined` (profile pending, or errored) counts as allowed: the app does
   * not know, and a verified student must not watch a dead button through a
   * page load. If it guesses wrong the run is refused, and
   * `correctionFailureMessage` now words that refusal properly.
   */
  const profile = useProfile()
  const emailVerified = profile.data?.emailVerified !== false
  const canStart = canStartRun({
    phase,
    hasScan: Boolean(scanFile),
    hasUploadedPaper: retryable,
    emailVerified,
  })
  const busy = running || waitingOnServer

  const panel = running
    ? { tone: "bg-accent", title: "Marking now" }
    : waitingOnServer
      ? { tone: "bg-accent", title: "Still marking" }
      : error || strandedStopped
        ? { tone: "bg-err", title: "Marking stopped" }
        : { tone: "bg-ok", title: "Ready when you are" }

  return (
    <div className="lm-screen flex flex-col gap-8">
      {/* §8.5's margin rule, the same single texture element the dashboard
          header carries. The Operate lane runs texture low (§13). */}
      <header className="margin-rule flex flex-wrap items-end gap-5">
        <div className="flex flex-col gap-1">
          <h1 className="text-display-lg text-ink">Correct a paper</h1>
          {/* max-w-[60ch] kept: a reading-measure width (character-count
           * based, not a pixel spacing value) — genuinely out of scope for
           * the 4px pixel scale, same reasoning as line-height ratios. */}
          <p className="max-w-[60ch] text-pretty text-body-md text-ink-muted">
            Scan or drop the paper. Lemely reads page one, identifies the exam,
            fetches the official mark scheme, and marks it.
          </p>
        </div>
        <div className="flex-1" />
        {/*
         * Hidden while a failure is on screen. The retry lives in the status
         * panel, beside the sentence explaining what went wrong and whether
         * the scan survived — and the first capture round showed both of them
         * rendering "Start marking again" at once, which is not the single
         * obvious primary action the Operate lane asks for (DESIGN.md §2).
         * One action, next to its reason.
         */}
        {(error || strandedStopped) && !running ? null : (
          <Button
            variant="primary"
            size="lg"
            onClick={runPipeline}
            loading={busy}
            disabled={!canStart}
          >
            {primaryLabel}
          </Button>
        )}
      </header>

      <div className="grid grid-correct-cols items-start gap-6 max-tablet:grid-cols-1">
        <Card className="flex flex-col gap-6 p-6">
          <div className="flex flex-col gap-3">
            <SourceToggle
              source={scanSource}
              onChoose={chooseScanSource}
              disabled={busy}
            />

            {scanSource === "file" ? (
              <FileDrop
                id="scan-file"
                label="Scanned paper"
                labelNote="required"
                accept="application/pdf,image/*"
                file={scanFile}
                onFileChange={chooseScan}
                busy={busy}
                clearLabel="Choose a different scan"
                hint="One paper per upload. Every page of it, in order."
              />
            ) : busy ? (
              <div className="rounded-lg border border-rule bg-paper-sunk px-4 py-3 text-body-sm text-ink-muted">
                {scanFile
                  ? `Scanned paper ready · ${scanFile.name}`
                  : "Marking in progress."}
              </div>
            ) : scanFile ? (
              <div className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-paper-raised px-4 py-3">
                <span className="min-w-0 flex-1 truncate text-body-sm text-ink">
                  Scan ready · {scanFile.name}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    chooseScan(null)
                    setCameraSessionKey((k) => k + 1)
                  }}
                >
                  Rescan
                </Button>
              </div>
            ) : (
              <CameraCapture
                key={cameraSessionKey}
                onComplete={chooseScan}
                onCancel={() => chooseScanSource("file")}
                className="border-0 bg-transparent p-0"
              />
            )}
          </div>

          {/* `compact`: the first capture round showed two identically sized
              drop zones stacked, which gave a reader nothing to tell the
              required upload from the optional one. The scheme field is the
              one almost nobody fills in — the whole point of the hint is that
              leaving it blank is the normal path — so it reads as secondary. */}
          <FileDrop
            id="scheme-file"
            label="Mark scheme"
            labelNote="optional"
            accept="application/pdf,image/*"
            file={schemeFile}
            onFileChange={setSchemeFile}
            busy={busy}
            size="compact"
            prompt="Drop your own scheme here, or choose one"
            clearLabel="Choose a different scheme"
            hint="Leave this blank and Lemely fetches the official scheme once it identifies the exam."
          />
        </Card>

        {/*
         * On a phone this column used to sit below the whole upload form, so
         * pressing "Mark this paper" scrolled everything that reports progress
         * roughly 1700px off the bottom of the screen. On the product's
         * longest, highest-latency flow, on the device its own brief says
         * students live on, the panel that says what is happening was the one
         * thing you could not see while it happened.
         *
         * Once a run is in flight or has failed, this column leads on mobile.
         * It does not on desktop, where both columns are visible at once and
         * reordering would move the form out from under the reader's cursor.
         */}
        <div
          className={cn(
            "flex flex-col gap-6",
            (running || error || strandedRun) && "max-tablet:order-first",
          )}
        >
          <Card className="flex flex-col gap-4 p-6">
            <div role="status" className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className={cn("h-2 w-2 rounded-full", panel.tone, busy && "animate-lm-pulse")}
              />
              <h2 className="text-display-sm text-ink">{panel.title}</h2>
            </div>

            {/*
             * PR 4, audit item deferred from PR 3: a failed `/uploads/active`
             * check used to be silent — `active.data` stayed `undefined`
             * forever, `strandedId` was never set, and a genuinely stranded
             * run was never surfaced. `compact` rather than `QueryState`'s
             * full panel: this must sit *alongside* the ordinary upload form,
             * not replace it — the reader can still start a fresh upload
             * while the check for an old one is failing, so this is additive
             * the way `QueryState`'s own exclusive skeleton/error/success
             * switch cannot render.
             *
             * Gated on `!running`: once this tab is streaming its own run,
             * whether some *other* run was also active is no longer a
             * question this screen has to answer.
             */}
            {active.isError && !running ? (
              <ErrorState
                compact
                heading="Couldn't check for a run already in progress"
                body={studentLoadFailureMessage(active.error)}
                action={{ label: "Try again", onClick: () => active.refetch() }}
              />
            ) : null}

            {strandedRun ? (
              <QueryState
                query={stranded}
                /*
                 * `useUploadRun` is `enabled: !!paperId` (see that hook), so
                 * with no `strandedId` it sits at `pending`/`fetchStatus:
                 * "idle"` forever — the `idle` trap `query-state.tsx`'s own
                 * header names. Unreachable here in practice: this branch
                 * only renders when `strandedRun` is truthy, which (see its
                 * definition above) only happens when `strandedId` is set —
                 * and that is exactly what enables `stranded`. `null` rather
                 * than inventing a state nothing can put the screen into.
                 */
                idle={null}
                /*
                 * While the fresh poll for THIS `strandedId` is in flight,
                 * `active.data` already names the same run (`strandedRun`
                 * falls back to it above, and this branch cannot be reached
                 * unless it is set) — shown instead of a shimmer skeleton,
                 * exactly as the pre-`QueryState` code did by falling back to
                 * it (`stranded.data ?? active.data`).
                 */
                skeleton={<StrandedRunPanel run={active.data!} onRetry={runPipeline} />}
                error={{
                  /*
                   * NEW: before this conversion a failed poll here fell back
                   * silently to `active.data` with no error shown and no way
                   * to retry beyond a full page reload — the poll's own
                   * `refetchInterval` kept firing, but a query that has
                   * settled into `status: "error"` needs a manual `refetch`
                   * to leave it, which nothing here ever called. `refetch`
                   * on `QueryState`'s retry button is that manual kick.
                   */
                  heading: "Couldn't check on this run",
                  body: studentLoadFailureMessage,
                }}
              >
                {(run) => <StrandedRunPanel run={run} onRetry={runPipeline} />}
              </QueryState>
            ) : (
              <ProcessingState
                stages={stages}
                footer={
                  error ? (
                    <div className="flex flex-col gap-3">
                      {/* The specific sentence lives on the failed stage, where
                          the failure is. This says what to do about it, which
                          is the part the audit found missing (M5) — not a
                          second copy of the error text. */}
                      <p className="text-body-sm text-ink-muted">
                        {retryable
                          ? "Your scan is already uploaded. Starting again re-marks the same file."
                          : "Nothing was uploaded, so starting again sends the file fresh."}
                      </p>
                      {/* Primary, not secondary: with the header action hidden
                          while a failure is showing, this is the screen's one
                          obvious next step. */}
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<ArrowClockwise size={16} />}
                        onClick={runPipeline}
                        disabled={!canStart}
                        className="self-start"
                      >
                        {retryLabel}
                      </Button>
                    </div>
                  ) : null
                }
              />
            )}
          </Card>

          <Card className="flex flex-col gap-4 p-6">
            <div className="flex flex-col gap-0.5">
              <h2 className="text-display-sm text-ink">How this gets marked</h2>
              <p className="text-body-sm text-ink-muted">
                Worth knowing before you trust the number
              </p>
            </div>
            <ul className="flex flex-col gap-3">
              {reassure.map((r) => (
                <li key={r.t} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-accent"
                  />
                  <span className="text-pretty text-body-sm text-ink-muted">{r.t}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}
