import { useState, type ChangeEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { ProcessingState, type ProcessingStage } from "@/components/ui/processing-state"
import { cn } from "@/lib/utils"
import { ApiError } from "@/lib/api"
import {
  advanceStage,
  annotateActiveStage,
  failActiveStage,
  frameProgress,
} from "@/lib/pipelineStages"
import { usePapers, usePaperDetail, uploadPaper, gradePaper } from "@/lib/hooks/useTeacherApi"
import type { DetectedField, PaperKind, PaperSummary, TeacherPipelineFrame } from "@/lib/teacherTypes"

/*
 * Grading. Wired to `GET /papers` (grid + tabs) via `usePapers()`,
 * `GET /papers/{id}` (left-sidebar Detected/Pipeline panels for the
 * *selected* paper) via `usePaperDetail()`, and the real upload -> grade
 * pipeline (`uploadPaper` + `gradePaper`, which chains extract+mark
 * internally on the backend — see `grade_paper_endpoint` in
 * `lemely/web/routers/teacher.py`: when a mark scheme is attached it calls
 * `extract_answers` then `grade_paper` in the same `run()` closure, so no
 * separate `extractPaper()` call is needed here).
 *
 * Cuts / judgment calls made vs. the mock (see `PaperListDTO`/`PaperDetailDTO`
 * in `lib/teacherTypes.ts`):
 *  - There is no batch concept backing "New batch · 0625/31 · May/June 2020" /
 *    "Grading 24 papers" — replaced with a generic "Grading console" caption
 *    and a live `Grading {papers.length} paper(s)` heading.
 *  - "Pause" button dropped — no backend concept.
 *  - The "Detected · MS 0625/31 v3 · Change" row above the tabs was
 *    batch-wide fake mark-scheme metadata with no backing source (mark
 *    schemes are attached per-paper at upload, not per-batch) — dropped.
 *  - Detected/Pipeline panels reflect the *selected* paper
 *    (`usePaperDetail(selectedPaperId)`), not a batch aggregate, since
 *    detection/pipeline data only exists per-paper. Selection defaults to
 *    whichever paper was most recently uploaded in this session (`undefined`
 *    before any upload); clicking a card also selects it.
 *  - Pipeline panel: `usePaperDetail` 409s until the paper is graded — shown
 *    as an honest idle state ("Not graded yet" / "Grading in progress…")
 *    instead of the mock's fabricated 5-step checklist.
 *  - "Drop more scans" dashed box + "Use custom mark scheme" button replaced
 *    by one real dual file-input upload control (scan required, mark scheme
 *    optional, matching `CorrectPaper.tsx`'s pattern) that auto-chains
 *    upload -> grade and streams progress into the stepper below it.
 *  - That progress readout used to be a raw scrolling text log (one line per
 *    SSE frame, `max-h-[140px] overflow-auto`). It is now a C-10
 *    `ProcessingState` stepper (S-14): three discrete stages, each with its own
 *    state, the spinner only on the one genuinely running, and the real
 *    "Question 7 of 21" counter the frames now carry. `describeFrame`'s text
 *    survived the swap — it is each stage's `detail` instead of a log line, so
 *    no wording was lost, only the unbounded scrollback. The state machine
 *    (advance / back-fill / annotate / fail / read the counter) is the shared
 *    reducer in `lib/pipelineStages.ts`, the same one behind the student
 *    panel, so the two portals cannot describe one pipeline two ways. See the
 *    note above `GRADING_STAGE_ORDER` for the stage this flow honestly omits,
 *    and `runGrading` for what closes the last stage and what happens when a
 *    single question fails mid-run.
 *  - `uploadError` state dropped with that log: a thrown `uploadPaper()` now
 *    fails the "upload" stage with the very same message, and printing it in
 *    two places would double-report one failure.
 *  - `autoGrade` donut now derives from the real `tabs` counts; the
 *    fabricated "~2 min remaining" ETA is replaced with a live
 *    "{n} processing" line (omitted when 0).
 *  - Paper cards: `pageCount` is always `null` today (no backend source), so
 *    the "12 pg" text is dropped rather than fabricated. The fake
 *    "0625/31 · MAY 2020" per-card caption is dropped too. The thumbnail
 *    container + its real-status overlays (review flag, processing spinner)
 *    are kept for visual continuity, but the fake page-line bars inside it
 *    are dropped (they implied per-paper scan content that doesn't exist).
 *  - `onOpen` on a card now selects the paper (updates the sidebar) instead
 *    of navigating to `/teacher/review`, which is queue-wide, not per-paper.
 */

const CIRC = 2 * Math.PI * 42

const PIPE_MARK = { done: "✓", active: "●", idle: "" } as const

const CHIP_TONE: Record<PaperKind, string> = {
  graded: "bg-ok-bg text-ok",
  review: "bg-err-bg text-err",
  processing: "bg-accent-subtle text-accent-subtle-on",
  queued: "bg-surface-2 text-t2",
}

type TabId = "all" | "review" | "graded" | "processing"

function filterPapers(papers: PaperSummary[], tab: TabId): PaperSummary[] {
  if (tab === "all") return papers
  if (tab === "processing") {
    return papers.filter((p) => p.kind === "processing" || p.kind === "queued")
  }
  return papers.filter((p) => p.kind === tab)
}

/** The stages this flow has real signal for, in the order the backend runs
 * them. Deliberately no "fetching the mark scheme" stage — the student panel
 * has one, this console must not: the teacher attaches the scheme at upload
 * time, so `grade_paper_endpoint` marks straight from `entry.mark_scheme` and
 * never emits a `mark_scheme_progress` frame. A stage no event could ever move
 * out of "pending" would read as stuck, not as honest.
 *
 * "upload" is not an SSE stage at all: it is the awaited `uploadPaper()` call,
 * which is real signal for exactly one thing — the POST is in flight, then it
 * returned (or threw). It earns a row because it is the slowest part of a
 * scan-sized request and the stream cannot begin until it lands. */
const GRADING_STAGE_ORDER = ["upload", "extract", "mark"] as const
type GradingStageId = (typeof GRADING_STAGE_ORDER)[number]

const initialGradingStages: ProcessingStage[] = [
  { id: "upload", label: "Uploading the scan", status: "pending" },
  { id: "extract", label: "Reading the answers", status: "pending" },
  { id: "mark", label: "Marking the questions", status: "pending" },
]

/** Which stage (if any) a frame type reports real progress for. */
function frameStageId(frame: TeacherPipelineFrame): GradingStageId | null {
  if (frame.type === "extraction_progress") return "extract"
  if (frame.type === "marking_progress") return "mark"
  return null
}

/** Human label for one SSE frame, used as the reported stage's detail text. */
function describeFrame(frame: TeacherPipelineFrame): string {
  switch (frame.type) {
    case "extraction_progress":
      return frame.question_id ? `Read question ${frame.question_id}` : "Reading answers"
    case "marking_progress":
      if (frame.question_id) {
        return frame.awarded != null && frame.max_marks != null
          ? `Marked question ${frame.question_id} — ${frame.awarded}/${frame.max_marks}`
          : `Marked question ${frame.question_id}`
      }
      return "Marking"
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

function PaperCard({
  paper,
  isGrading,
  onOpen,
}: {
  paper: PaperSummary
  isGrading: boolean
  onOpen: () => void
}) {
  const showSpinner = paper.kind === "processing" || (paper.kind === "queued" && isGrading)
  const confTone =
    paper.kind === "review" ? "text-err" : paper.kind === "graded" ? "text-t2" : "text-t3"
  const confText = paper.confidence != null ? `conf ${Math.round(paper.confidence * 100)}%` : null
  const scoreText =
    paper.awardedMarks != null && paper.maxMarks != null
      ? `${paper.awardedMarks}/${paper.maxMarks}`
      : "-"

  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onOpen()
        }
      }}
      className={cn(
        "rounded-md overflow-hidden bg-surface cursor-pointer transition-transform hover:-translate-y-0.5 border",
        paper.kind === "review" ? "border-err" : "border-border",
      )}
    >
      <div className="relative h-[64px] bg-surface-2 border-b border-border overflow-hidden">
        {paper.kind === "review" ? (
          <div className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-err text-accent-on text-3xs flex items-center justify-center font-mono">
            !
          </div>
        ) : null}
        {showSpinner ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-[26px] h-[26px] rounded-full border-[3px] border-border border-t-accent animate-spin" />
          </div>
        ) : null}
      </div>
      <div className="px-[13px] py-3">
        <div className="flex items-center gap-2">
          <div className="text-dense-lg font-medium flex-1">{paper.name}</div>
          <div
            className={cn(
              "text-3xs rounded-full px-[9px] py-0.5",
              CHIP_TONE[paper.kind],
            )}
          >
            {paper.status}
          </div>
        </div>
        <div className="flex items-baseline gap-2 mt-[9px]">
          {confText ? (
            <div className={cn("font-mono text-xs", confTone)}>{confText}</div>
          ) : null}
          <div className="flex-1" />
          <div className="font-mono text-md">{scoreText}</div>
        </div>
      </div>
    </div>
  )
}

export function Grading() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<TabId>("all")
  const [selectedPaperId, setSelectedPaperId] = useState<string | undefined>(undefined)
  const [detectedByPaper, setDetectedByPaper] = useState<Record<string, DetectedField[]>>({})
  const [gradingIds, setGradingIds] = useState<Record<string, boolean>>({})
  const [scanFile, setScanFile] = useState<File | null>(null)
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [stages, setStages] = useState<ProcessingStage[]>(initialGradingStages)

  const papersQuery = usePapers()
  const paperDetailQuery = usePaperDetail(selectedPaperId)

  const runGrading = async (paperId: string) => {
    setGradingIds((prev) => ({ ...prev, [paperId]: true }))
    // Set once a frame has failed a stage. Two jobs. It stops the stepper
    // advancing, because `advanceStage` would otherwise flip the failed stage
    // straight back to "active" on the next `marking_progress` and the failure
    // would vanish from the panel. And it lets us keep *draining* the stream
    // rather than returning: a per-question `error` from `correct_paper` is not
    // fatal — the backend marks the remaining questions and only then publishes
    // done — so bailing out early would drop the card spinner and refetch the
    // grid while the run was still going, which is a worse lie than the one we
    // are avoiding.
    let failed = false
    try {
      for await (const frame of gradePaper(paperId)) {
        if (frame.type === "warning" || frame.type === "error") {
          // `describeFrame`'s default branch is the backend's own `message`,
          // falling back to the raw frame type when it sent none — never
          // invented prose, per C-10's no-generic-fallback rule.
          const message = describeFrame(frame)
          setStages((prev) => failActiveStage(prev, message))
          failed = true
          continue
        }
        if (failed) continue
        const stageId = frameStageId(frame)
        const progress = frameProgress(frame)
        if (stageId) {
          // This endpoint has no terminal frame — the student route's
          // `phase: "complete"` summary belongs to `/student/correct`, not
          // here — so the only real completion signal is the counter reaching
          // its own denominator. Both publishers walk their work list with
          // `enumerate`, so `index === total` is the last question of that
          // stage, and nothing else follows it. Without this the stage that
          // just finished would keep spinning until the next stage's first
          // frame, and the final stage would spin forever.
          const complete = progress != null && progress.current >= progress.total
          setStages((prev) =>
            advanceStage(
              prev,
              GRADING_STAGE_ORDER,
              stageId,
              describeFrame(frame),
              complete,
              progress,
            ),
          )
        } else {
          setStages((prev) => annotateActiveStage(prev, describeFrame(frame)))
        }
      }
      if (!failed) {
        // The stream closed with no error frame. That is the happy path when
        // every stage reported finishing — but `grade_paper_endpoint` publishes
        // done from a `finally`, so an exception inside its worker thread also
        // ends the stream cleanly, with nothing said about it. Leaving the
        // spinner running would claim work still in flight; calling it done
        // would claim marks that do not exist. Report the one thing actually
        // observed: the stream stopped early. The refetched grid below is the
        // authority on whether the paper ended up graded.
        setStages((prev) =>
          prev.every((s) => s.status === "done")
            ? prev
            : failActiveStage(prev, "The grading stream ended before this stage finished."),
        )
      }
    } catch (err) {
      setStages((prev) =>
        failActiveStage(prev, err instanceof Error ? err.message : String(err)),
      )
    } finally {
      setGradingIds((prev) => {
        const next = { ...prev }
        delete next[paperId]
        return next
      })
      queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "paper", paperId] })
    }
  }

  const handleUpload = async () => {
    if (!scanFile || uploading) return
    setUploading(true)
    // Reset to a fresh stepper and open the upload stage in one go — a second
    // run must not inherit the first one's ticks or its error.
    setStages(
      advanceStage(
        initialGradingStages,
        GRADING_STAGE_ORDER,
        "upload",
        scanFile.name,
        false,
      ),
    )
    try {
      const { paperId, detected } = await uploadPaper(scanFile, schemeFile ?? undefined)
      // `undefined` detail keeps the file name already on the row.
      setStages((prev) => advanceStage(prev, GRADING_STAGE_ORDER, "upload", undefined, true))
      setDetectedByPaper((prev) => ({ ...prev, [paperId]: detected }))
      setSelectedPaperId(paperId)
      setScanFile(null)
      setSchemeFile(null)
      queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })
      await runGrading(paperId)
    } catch (err) {
      // Only `uploadPaper` can reach here — `runGrading` reports its own
      // failures into the stepper and never rethrows — so this fails the
      // "upload" stage, which is still the running one at that point.
      setStages((prev) =>
        failActiveStage(prev, err instanceof Error ? err.message : String(err)),
      )
    } finally {
      setUploading(false)
    }
  }

  const handleScanChange = (e: ChangeEvent<HTMLInputElement>) => {
    setScanFile(e.target.files?.[0] ?? null)
  }
  const handleSchemeChange = (e: ChangeEvent<HTMLInputElement>) => {
    setSchemeFile(e.target.files?.[0] ?? null)
  }

  if (papersQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-dense-lg text-t2">Loading papers…</div>
      </div>
    )
  }

  if (papersQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-dense-lg text-accent">
          Couldn't load papers: {papersQuery.error.message}
        </div>
      </div>
    )
  }

  const { papers, tabs } = papersQuery.data
  const filtered = filterPapers(papers, tab)

  const allCount = Number(tabs.find((t) => t.id === "all")?.count ?? "0")
  const gradedCount = Number(tabs.find((t) => t.id === "graded")?.count ?? "0")
  const reviewCount = Number(tabs.find((t) => t.id === "review")?.count ?? "0")
  const processingCount = Number(tabs.find((t) => t.id === "processing")?.count ?? "0")
  const progress = allCount > 0 ? gradedCount / allCount : 0
  const dash = `${(CIRC * progress).toFixed(1)} ${CIRC.toFixed(1)}`

  const detectedFields: DetectedField[] = selectedPaperId
    ? (paperDetailQuery.data?.metadata ?? detectedByPaper[selectedPaperId] ?? [])
    : []

  const hasRunStarted = stages.some((s) => s.status !== "pending")

  const isSelectedPaperNotGraded =
    paperDetailQuery.isError &&
    paperDetailQuery.error instanceof ApiError &&
    paperDetailQuery.error.status === 409

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-2xs tracking-[0.11em] uppercase text-t3">
            Grading console
          </div>
          {/* A real h1, not a styled div: axe's `page-has-heading-one` fired
              on this route the moment P3.10 chunk b added it to the audit
              registry, and QUALITY-BAR.md requires one h1 per page. */}
          <h1 className="text-display-md mt-1.5">
            Grading {papers.length} paper{papers.length === 1 ? "" : "s"}
          </h1>
        </div>
        <div className="flex-1" />
        <Button variant="ink" onClick={() => navigate("/teacher/review")}>
          Open review queue →
        </Button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-6 items-start">
        {/* Left column */}
        <div className="flex flex-col gap-4">
          <div className="bg-surface border border-border rounded-lg px-5 py-[18px]">
            <div className="font-mono text-3xs tracking-[0.1em] uppercase text-t3">
              Detected
            </div>
            {!selectedPaperId ? (
              <div className="text-dense text-t2 mt-[18px]">
                Upload a scan to see detected fields.
              </div>
            ) : detectedFields.length === 0 ? (
              <div className="text-dense text-t2 mt-[18px]">
                No metadata detected for this paper.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-x-[14px] gap-y-4 mt-[18px]">
                {detectedFields.map((d) => (
                  <div key={d.key}>
                    <div className="font-mono text-3xs tracking-[0.1em] uppercase text-t3">
                      {d.key}
                    </div>
                    <div className="font-mono text-md mt-1">{d.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-surface border border-border rounded-lg p-5 flex gap-5 items-center">
            <svg
              viewBox="0 0 100 100"
              className="w-[92px] h-[92px] flex-none -rotate-90"
            >
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="var(--border)"
                strokeWidth="10"
              />
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="var(--accent)"
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={dash}
              />
            </svg>
            <div className="flex-1">
              <div className="text-md font-semibold">Auto-grading</div>
              {processingCount > 0 ? (
                <div className="font-mono text-xs text-t2 mt-[5px]">
                  {processingCount} processing
                </div>
              ) : null}
              <div className="flex gap-[22px] mt-[14px]">
                <div>
                  <div className="text-display-sm">{gradedCount}</div>
                  <div className="font-mono text-3xs text-t3 mt-[3px]">
                    AUTO-CONFIRMED
                  </div>
                </div>
                <div>
                  <div className="text-display-sm text-err">
                    {reviewCount}
                  </div>
                  <div className="font-mono text-3xs text-t3 mt-[3px]">
                    NEED REVIEW
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface border border-border rounded-lg px-5 py-[18px]">
            <div className="font-mono text-3xs tracking-[0.1em] uppercase text-t3 mb-[14px]">
              Pipeline
            </div>
            {!selectedPaperId ? (
              <div className="text-dense text-t2">Upload a scan to see its pipeline.</div>
            ) : paperDetailQuery.isPending ? (
              <div className="text-dense text-t2">Loading…</div>
            ) : isSelectedPaperNotGraded ? (
              <div className="text-dense text-t2">
                {gradingIds[selectedPaperId] ? "Grading in progress…" : "Not graded yet."}
              </div>
            ) : paperDetailQuery.isError ? (
              <div className="text-dense text-accent">
                Couldn't load pipeline: {paperDetailQuery.error.message}
              </div>
            ) : (
              paperDetailQuery.data.pipeline.map((p) => (
                <div key={p.label} className="flex items-center gap-3 py-[9px]">
                  <span
                    className={cn(
                      "w-[19px] h-[19px] flex-none rounded-full border-[1.5px] flex items-center justify-center text-3xs font-mono",
                      p.state === "done"
                        ? "bg-ok border-ok text-accent-on"
                        : p.state === "active"
                          ? "bg-transparent border-accent text-accent"
                          : "bg-transparent border-border text-accent",
                    )}
                  >
                    {PIPE_MARK[p.state]}
                  </span>
                  <span
                    className={cn(
                      "flex-1 text-dense-lg",
                      p.state === "idle" ? "text-t3" : "text-t1",
                    )}
                  >
                    {p.label}
                  </span>
                  <span className="font-mono text-xs text-t2">{p.count}</span>
                </div>
              ))
            )}
          </div>

          <div className="border border-border rounded-lg p-5 bg-surface-2 flex flex-col gap-3">
            <div className="text-sm font-medium">Upload a scan</div>
            <div>
              <label
                htmlFor="grading-scan-file"
                className="text-xs font-medium block mb-1.5"
              >
                Scanned paper
              </label>
              <input
                id="grading-scan-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleScanChange}
                className="text-xs text-t2 file:mr-3 file:border file:border-border file:bg-surface file:rounded-lg file:px-3 file:py-1.5 file:text-xs file:cursor-pointer file:font-sans"
              />
            </div>
            <div>
              <label
                htmlFor="grading-scheme-file"
                className="text-xs font-medium block mb-1.5"
              >
                Mark scheme (optional)
              </label>
              <input
                id="grading-scheme-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleSchemeChange}
                className="text-xs text-t2 file:mr-3 file:border file:border-border file:bg-surface file:rounded-lg file:px-3 file:py-1.5 file:text-xs file:cursor-pointer file:font-sans"
              />
              {!schemeFile ? (
                <div className="font-mono text-3xs text-t3 mt-1.5">
                  Attach a mark scheme to enable grading — otherwise the scan is
                  uploaded but nothing gets marked.
                </div>
              ) : null}
            </div>
            <Button
              variant="ink"
              size="sm"
              onClick={handleUpload}
              disabled={uploading || !scanFile}
            >
              {/* Not "Uploading…": `uploading` stays true for the whole
                  upload -> extract -> mark chain, so that label went on
                  claiming an upload was in flight while the stepper below
                  correctly showed it ticked and marking running. The button
                  says only what it knows; the stage rows carry the specifics. */}
              {uploading ? "Working…" : "Upload & grade"}
            </Button>
            {/* Hidden until a run has actually touched a stage: three pending
                rows sitting under an empty file input would be a promise, not
                a report. Errors surface on the stage that failed, so there is
                no separate error line here to contradict it. */}
            {hasRunStarted ? (
              <ProcessingState stages={stages} className="border-t border-border pt-4" />
            ) : null}
          </div>
        </div>

        {/* Right column: tabs + papers */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-[14px] flex-wrap">
            <div className="flex gap-1 bg-surface-2 p-1 rounded-md">
              {tabs.map((t) => {
                const on = tab === t.id
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={cn(
                      "border-0 cursor-pointer text-dense px-[14px] py-2 rounded-lg",
                      on
                        ? "bg-surface text-t1 font-medium shadow-sm"
                        : "bg-transparent text-t2 font-normal",
                    )}
                  >
                    {t.label}{" "}
                    <span
                      className={cn(
                        "font-mono text-xs",
                        on ? "text-accent" : "text-t3",
                      )}
                    >
                      {t.count}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.length === 0 ? (
              <div className="text-dense text-t2">No papers in this view yet.</div>
            ) : (
              filtered.map((p) => (
                <PaperCard
                  key={p.id}
                  paper={p}
                  isGrading={!!gradingIds[p.id]}
                  onOpen={() => setSelectedPaperId(p.id)}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
