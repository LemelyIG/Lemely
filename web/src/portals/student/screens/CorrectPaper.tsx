/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowClockwise, Camera, UploadSimple } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { FileDrop } from "@/components/ui/file-drop"
import { ProcessingState, type ProcessingStage } from "@/components/ui/processing-state"
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
import { runCorrection, uploadScan } from "@/lib/hooks/useStudentApi"
import { cn } from "@/lib/utils"
import type { QuestionResult, Result, StudentCorrectFrame } from "@/lib/studentTypes"
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
 */

/** The three stages the backend's SSE frames give us real signal for. Spec
 * S-14 also lists "identifying the paper" and "analysing your weak topics" —
 * omitted here because no frame type announces the start/end of either; a
 * stage with no event that could ever move it out of "pending" would look
 * stuck rather than honest. Flagged in the P2.5.3 report as a content gap. */
const STAGE_ORDER = ["extract", "scheme", "mark"] as const
type StageId = (typeof STAGE_ORDER)[number]

const initialStages: ProcessingStage[] = [
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

  const runPipeline = async () => {
    if (!scanFile || running) return
    setRunning(true)
    setError(null)
    setStages(initialStages)
    try {
      // M5's retry: only upload when there is nothing on the server yet.
      let id = paperId
      if (!canRetryInPlace(id)) {
        const uploaded = await uploadScan(scanFile, schemeFile ?? undefined)
        id = uploaded.paperId
        setPaperId(id)
      }
      await streamCorrection(id)
    } catch (err) {
      const message = correctionFailureMessage(err)
      setStages((prev) => failActiveStage(prev, message))
      setError(message)
    } finally {
      setRunning(false)
    }
  }

  const retryable = canRetryInPlace(paperId)
  const primaryLabel = running ? "Marking…" : "Mark this paper"
  const retryLabel = retryable ? "Start marking again" : "Try again"

  const panel = running
    ? { tone: "bg-accent", title: "Marking now" }
    : error
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
        {error && !running ? null : (
          <Button variant="primary" size="lg" onClick={runPipeline} loading={running} disabled={!scanFile}>
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
              disabled={running}
            />

            {scanSource === "file" ? (
              <FileDrop
                id="scan-file"
                label="Scanned paper"
                labelNote="required"
                accept="application/pdf,image/*"
                file={scanFile}
                onFileChange={chooseScan}
                busy={running}
                clearLabel="Choose a different scan"
                hint="One paper per upload. Every page of it, in order."
              />
            ) : running ? (
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
            busy={running}
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
            (running || error) && "max-tablet:order-first",
          )}
        >
          <Card className="flex flex-col gap-4 p-6">
            <div role="status" className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className={cn("h-2 w-2 rounded-full", panel.tone, running && "animate-lm-pulse")}
              />
              <h2 className="text-display-sm text-ink">{panel.title}</h2>
            </div>

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
                      disabled={!scanFile}
                      className="self-start"
                    >
                      {retryLabel}
                    </Button>
                  </div>
                ) : null
              }
            />
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
