/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type ChangeEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { ProcessingState, type ProcessingStage } from "@/components/ui/processing-state"
import { cn } from "@/lib/utils"
import { CardGridSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import { failActiveStage } from "@/lib/pipelineStages"
import { useInViewOnce } from "@/lib/hooks/useInViewOnce"
import {
  usePapers,
  usePaperDetail,
  useRegradePaper,
  useScanPreview,
  uploadPaper,
} from "@/lib/hooks/useTeacherApi"
import type { PaperKind, PaperSummary } from "@/lib/teacherTypes"

/*
 * Grading. Wired to `GET /papers` (grid + tabs) via `usePapers()` and
 * `GET /papers/{id}` (left-sidebar Detected/Pipeline panels for the *selected*
 * paper) via `usePaperDetail()`, plus the real upload (`uploadPaper`).
 *
 * ── Who runs the marking (D6.13) ─────────────────────────────────────────
 * The server does, on its own worker, starting the moment the scan lands. This
 * screen does not drive it and cannot stall it.
 *
 * It used to. `handleUpload` awaited `uploadPaper()` and then held a
 * `POST /papers/{id}/grade` SSE stream open for the whole run, which made the
 * browser tab load-bearing: nothing marked a paper unless a console was
 * watching it. That turned an unrelated backend defect — `upload_paper` ran a
 * ~60s synchronous Gemini call inside an `async def`, freezing uvicorn's only
 * event loop — into a permanent stall, because the upload `fetch` never
 * resolved, so `runGrading()` was never reached and no grade request was ever
 * issued. The console sat on "Queued" indefinitely and a page refresh cleared
 * the only progress readout that existed, since it was component state.
 *
 * So the SSE consumption is gone from this screen, and the Pipeline panel reads
 * `GET /papers/{id}` instead — which now answers for papers still being marked
 * (it used to 409 until a report existed) and carries the live stage plus the
 * real per-question counter. Server state survives a refresh; component state
 * never could. `usePapers`/`usePaperDetail` poll only while something is
 * actually in flight, so an idle console makes no requests.
 *
 * That leaves ONE reporter per fact, which is the property the old design lost:
 * the stepper under the upload control speaks only for the upload (the one
 * thing this browser does), and the Pipeline panel speaks for the run.
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
 *  - Detected/Pipeline panels reflect the *selected* paper, not a batch
 *    aggregate, since detection/pipeline data only exists per-paper. Selection
 *    defaults to whichever paper was most recently uploaded in this session;
 *    clicking a card also selects it.
 *  - "Drop more scans" dashed box + "Use custom mark scheme" button replaced
 *    by one real dual file-input upload control (scan required, mark scheme
 *    optional, matching `CorrectPaper.tsx`'s pattern).
 *  - `autoGrade` donut derives from the real `tabs` counts; the fabricated
 *    "~2 min remaining" ETA is replaced with a live "{n} processing" line
 *    (omitted when 0).
 *  - Paper cards: `pageCount` is always `null` today (no backend source), so
 *    the "12 pg" text is dropped rather than fabricated. The thumbnail is the
 *    real first page of the scan, rendered server-side by
 *    `GET /papers/{id}/preview`; the mock's fake page-line bars are gone.
 *  - `onOpen` on a card selects the paper (updates the sidebar) instead of
 *    navigating to `/teacher/review`, which is queue-wide, not per-paper.
 */

const CIRC = 2 * Math.PI * 42

const PIPE_MARK = { done: "✓", active: "●", idle: "" } as const

const CHIP_TONE: Record<PaperKind, string> = {
  graded: "bg-ok-wash text-ok",
  review: "bg-err-wash text-err",
  processing: "bg-accent-wash text-accent-ink",
  queued: "bg-paper-sunk text-ink-muted",
  // Distinct from `review`'s red: review means "a human should look at these
  // marks", failed means "there are no marks". Reading as the same state would
  // send a teacher hunting for a score that was never produced.
  failed: "bg-paper-sunk text-err border border-err",
}

type TabId = "all" | "review" | "graded" | "processing"

function filterPapers(papers: PaperSummary[], tab: TabId): PaperSummary[] {
  if (tab === "all") return papers
  if (tab === "processing") {
    return papers.filter((p) => p.kind === "processing" || p.kind === "queued")
  }
  return papers.filter((p) => p.kind === tab)
}

/* The upload control's own stepper. One stage, because one stage is all this
 * browser does: the POST is in flight, then it landed (or it didn't). Marking
 * is reported by the Pipeline panel, from the server. A row here for "Reading
 * the answers" would be this screen guessing at work it no longer performs. */
const UPLOAD_STAGES: ProcessingStage[] = [
  { id: "upload", label: "Uploading the scan", status: "pending" },
]

function PaperCard({
  paper,
  onOpen,
}: {
  paper: PaperSummary
  onOpen: () => void
}) {
  /* P6.3. The thumbnail's bytes come from a server-side render of the stored
     scan, so the deferral has to gate the *fetch*; `loading="lazy"` on the
     `<img>` below would defer nothing, because by then the blob is already
     local. A callback ref rather than `useRef`, because mutating `.current`
     does not re-run `useInViewOnce`'s effect. */
  const [cardNode, setCardNode] = useState<HTMLDivElement | null>(null)
  const nearViewport = useInViewOnce(cardNode)
  const previewUrl = useScanPreview(paper.id, nearViewport)
  const showSpinner = paper.kind === "processing"
  const confTone =
    paper.kind === "review" ? "text-err" : paper.kind === "graded" ? "text-ink-muted" : "text-ink-faint"
  const confText = paper.confidence != null ? `conf ${Math.round(paper.confidence * 100)}%` : null
  const scoreText =
    paper.awardedMarks != null && paper.maxMarks != null
      ? `${paper.awardedMarks}/${paper.maxMarks}`
      : "-"

  return (
    <div
      ref={setCardNode}
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
        "rounded-md overflow-hidden bg-paper-raised cursor-pointer transition-transform hover:-translate-y-0.5 border",
        paper.kind === "review" ? "border-err" : "border-rule",
      )}
    >
      <div className="relative h-[64px] bg-paper-sunk border-b border-rule overflow-hidden">
        {previewUrl ? (
          // Top-anchored: a scan's identifying marks (subject, paper number,
          // candidate box) are at the head of page 1, so a 64px window onto the
          // top of the page is the part worth showing. `alt` is empty because
          // the card's own name/status text already names this paper — a
          // screen-reader would otherwise hear the same paper announced twice.
          <img
            src={previewUrl}
            alt=""
            className="w-full h-full object-cover object-top"
          />
        ) : null}
        {paper.kind === "review" ? (
          <div className="absolute top-2.5 end-2.5 w-5 h-5 rounded-full bg-err text-accent-on text-data-sm flex items-center justify-center">
            !
          </div>
        ) : null}
        {showSpinner ? (
          <div className="absolute inset-0 flex items-center justify-center bg-paper-sunk/70">
            <div className="w-[26px] h-[26px] rounded-full border-[3px] border-rule border-t-accent animate-spin" />
          </div>
        ) : null}
      </div>
      <div className="px-[13px] py-3">
        <div className="flex items-center gap-2">
          {/* `min-w-0` + `truncate`: a flex child's default `min-width: auto`
              refuses to shrink below its content, so a long name (the detected
              label is longer still — "Paper 1 V2 May/June 2020 - 2026-08-12")
              pushed the status chip off the card's right edge and clipped it. */}
          <div className="text-body-lg font-medium flex-1 min-w-0 truncate" title={paper.name}>
            {paper.name}
          </div>
          <div
            className={cn(
              "text-eyebrow rounded-full px-[9px] py-1 whitespace-nowrap flex-none",
              CHIP_TONE[paper.kind],
            )}
          >
            {paper.status}
          </div>
        </div>
        <div className="flex items-baseline gap-2 mt-[9px]">
          {confText ? (
            <div className={cn("text-data-sm", confTone)}>{confText}</div>
          ) : null}
          <div className="flex-1" />
          <div className="text-data-md text-ink">{scoreText}</div>
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
  const [scanFile, setScanFile] = useState<File | null>(null)
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [stages, setStages] = useState<ProcessingStage[]>(UPLOAD_STAGES)

  const papersQuery = usePapers()
  /* What the sidebar reports when the teacher has not picked a paper.
   *
   * A reload resets `selectedPaperId` to undefined, and with nothing selected
   * the Detected and Pipeline panels have nothing to show — which is what made
   * refreshing mid-run look like the pipeline had vanished, even after the
   * server started answering for ungraded papers. Defaulting to the paper
   * actually being marked (else the newest one) means the console comes back up
   * pointed at the run in progress, which is what a teacher reloaded the page
   * to find out about. An explicit click still wins. */
  const papers = papersQuery.data?.papers ?? []
  const defaultPaperId =
    papers.find((p) => p.kind === "processing")?.id ??
    papers.find((p) => p.kind === "queued")?.id ??
    papers[papers.length - 1]?.id
  const activePaperId = selectedPaperId ?? defaultPaperId
  const paperDetailQuery = usePaperDetail(activePaperId)
  const regrade = useRegradePaper()

  const handleUpload = async () => {
    if (!scanFile || uploading) return
    setUploading(true)
    // Reset to a fresh stepper and open the upload stage in one go — a second
    // run must not inherit the first one's tick or its error.
    setStages([{ id: "upload", label: "Uploading the scan", status: "active", detail: scanFile.name }])
    try {
      const { paperId } = await uploadPaper(scanFile, schemeFile ?? undefined)
      setStages((prev) => prev.map((s) => ({ ...s, status: "done" })))
      // Select it so the Pipeline panel starts reporting the run the server has
      // already begun — this is the handover from "what this tab did" to "what
      // the server is doing".
      setSelectedPaperId(paperId)
      setScanFile(null)
      setSchemeFile(null)
      queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })
    } catch (err) {
      /* P6.2. This put `err.message` on the failed stage, so a dropped
         connection during a class upload wrote the browser's "Failed to fetch"
         into the pipeline panel, and a 500 wrote its status line. C-10 requires
         a specific, actionable message per stage and this was neither.
         `teacherMutationFailureMessage` is the mutation half of this portal's
         own module: status-first, because every `detail` the staff upload path
         raises is written for a client author. */
      setStages((prev) => failActiveStage(prev, teacherMutationFailureMessage(err)))
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
        <CardGridSkeleton count={6} />
      </div>
    )
  }

  if (papersQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-body-lg text-accent-ink">
          Couldn't load papers: {teacherLoadFailureMessage(papersQuery.error)}
        </div>
      </div>
    )
  }

  // `papers` is already bound above (the default-selection needs it before the
  // pending/error early-returns, where `papersQuery.data` may not exist yet).
  const { tabs } = papersQuery.data
  const filtered = filterPapers(papers, tab)

  const allCount = Number(tabs.find((t) => t.id === "all")?.count ?? "0")
  const gradedCount = Number(tabs.find((t) => t.id === "graded")?.count ?? "0")
  const reviewCount = Number(tabs.find((t) => t.id === "review")?.count ?? "0")
  const processingCount = Number(tabs.find((t) => t.id === "processing")?.count ?? "0")
  const progress = allCount > 0 ? gradedCount / allCount : 0
  const dash = `${(CIRC * progress).toFixed(1)} ${CIRC.toFixed(1)}`

  const detail = paperDetailQuery.data
  const detectedFields = detail?.metadata ?? []
  const hasRunStarted = stages.some((s) => s.status !== "pending")

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-rule flex-wrap gap-y-2.5">
        <div>
          <div className="text-eyebrow text-ink-faint">
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
          <div className="bg-paper-raised border border-rule rounded-lg px-5 py-[18px]">
            <div className="text-eyebrow text-ink-faint">
              Detected
            </div>
            {!activePaperId ? (
              <div className="text-body-md text-ink-muted mt-[18px]">
                Upload a scan to see detected fields.
              </div>
            ) : detectedFields.length === 0 ? (
              // Detection is the first phase of the server-side run, so an
              // in-flight paper genuinely has no answer yet — say which of the
              // two it is rather than reporting "none" for both.
              <div className="text-body-md text-ink-muted mt-[18px]">
                {detail && (detail.kind === "queued" || detail.kind === "processing")
                  ? "Reading this scan's exam details…"
                  : "No metadata detected for this paper."}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-x-[14px] gap-y-4 mt-[18px]">
                {detectedFields.map((d) => (
                  <div key={d.key}>
                    <div className="text-eyebrow text-ink-faint">
                      {d.key}
                    </div>
                    <div className="text-data-md text-ink mt-1">{d.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-paper-raised border border-rule rounded-lg p-5 flex gap-5 items-center">
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
              <div className="text-display-sm text-ink">Auto-grading</div>
              {processingCount > 0 ? (
                <div className="text-data-sm text-ink-faint mt-[5px]">
                  {processingCount} processing
                </div>
              ) : null}
              <div className="flex gap-[22px] mt-[14px]">
                <div>
                  <div className="text-display-sm">{gradedCount}</div>
                  <div className="text-data-sm text-ink-faint mt-[3px]">
                    AUTO-CONFIRMED
                  </div>
                </div>
                <div>
                  <div className="text-display-sm text-err">
                    {reviewCount}
                  </div>
                  <div className="text-data-sm text-ink-faint mt-[3px]">
                    NEED REVIEW
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-paper-raised border border-rule rounded-lg px-5 py-[18px]">
            <div className="text-eyebrow text-ink-faint mb-[14px]">
              Pipeline
            </div>
            {!activePaperId ? (
              <div className="text-body-md text-ink-muted">Upload a scan to see its pipeline.</div>
            ) : paperDetailQuery.isPending ? (
              <div className="text-body-md text-ink-muted">Loading…</div>
            ) : paperDetailQuery.isError ? (
              <div className="text-body-md text-accent-ink">
                Couldn't load pipeline: {teacherLoadFailureMessage(paperDetailQuery.error)}
              </div>
            ) : detail ? (
              <>
                {detail.pipeline.map((p) => (
                  <div key={p.label} className="flex items-center gap-3 py-[9px]">
                    <span
                      className={cn(
                        "w-[19px] h-[19px] flex-none rounded-full border-[1.5px] flex items-center justify-center text-data-sm",
                        p.state === "done"
                          ? "bg-ok border-ok text-accent-on"
                          : p.state === "active"
                            ? "bg-transparent border-accent text-accent-ink"
                            : "bg-transparent border-rule text-accent-ink",
                      )}
                    >
                      {PIPE_MARK[p.state]}
                    </span>
                    <span
                      className={cn(
                        "flex-1 text-body-lg",
                        p.state === "idle" ? "text-ink-faint" : "text-ink",
                      )}
                    >
                      {p.label}
                    </span>
                    <span className="text-data-sm text-ink-faint">{p.count}</span>
                  </div>
                ))}
                {detail.kind === "queued" ? (
                  <div className="text-body-md text-ink-muted mt-2">
                    Waiting for the marking worker.
                  </div>
                ) : null}
                {detail.error ? (
                  // The specific reason, from the server — never a generic
                  // "something went wrong". A paper that produced no marks has
                  // to say why, or the teacher has nothing to act on.
                  <div className="mt-3 pt-3 border-t border-rule flex flex-col gap-2.5 items-start">
                    <div className="text-body-md text-err">{detail.error}</div>
                    <Button
                      variant="ink"
                      size="sm"
                      disabled={regrade.isPending}
                      onClick={() => regrade.mutate(detail.id)}
                    >
                      {regrade.isPending ? "Queueing…" : "Try again"}
                    </Button>
                    {regrade.isError ? (
                      <div className="text-body-md text-err">
                        Couldn't re-queue: {teacherMutationFailureMessage(regrade.error)}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
          </div>

          <div className="border border-rule rounded-lg p-5 bg-paper-sunk flex flex-col gap-3">
            <div className="text-body-md font-medium">Upload a scan</div>
            <div>
              <label
                htmlFor="grading-scan-file"
                className="text-body-sm font-medium block mb-1.5"
              >
                Scanned paper
              </label>
              <input
                id="grading-scan-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleScanChange}
                className="text-body-sm text-ink-muted file:me-3 file:border file:border-rule file:bg-paper-raised file:rounded-lg file:px-3 file:py-1.5 file:text-body-sm file:cursor-pointer file:font-sans"
              />
            </div>
            <div>
              <label
                htmlFor="grading-scheme-file"
                className="text-body-sm font-medium block mb-1.5"
              >
                Mark scheme (optional)
              </label>
              <input
                id="grading-scheme-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleSchemeChange}
                className="text-body-sm text-ink-muted file:me-3 file:border file:border-rule file:bg-paper-raised file:rounded-lg file:px-3 file:py-1.5 file:text-body-sm file:cursor-pointer file:font-sans"
              />
              {!schemeFile ? (
                <div className="text-data-sm text-ink-faint mt-1.5">
                  Attach a mark scheme unless you've already uploaded one for this
                  paper — without either, there is nothing to mark against.
                </div>
              ) : null}
            </div>
            <Button
              variant="ink"
              size="sm"
              onClick={handleUpload}
              disabled={uploading || !scanFile}
            >
              {uploading ? "Uploading…" : "Upload & grade"}
            </Button>
            {/* Hidden until an upload has actually been attempted: a pending row
                sitting under an empty file input would be a promise, not a
                report. Errors surface on the stage that failed, so there is no
                separate error line here to contradict it. */}
            {hasRunStarted ? (
              <>
                <ProcessingState stages={stages} className="border-t border-rule pt-4" />
                {stages.every((s) => s.status === "done") ? (
                  <div className="text-body-md text-ink-muted">
                    Marking runs on the server, so it keeps going if you close this
                    page. Progress is in Pipeline above.
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {/* Right column: tabs + papers */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-[14px] flex-wrap">
            <div className="flex gap-1 bg-paper-sunk p-1 rounded-md">
              {tabs.map((t) => {
                const on = tab === t.id
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={cn(
                      "border-0 cursor-pointer text-body-md px-[14px] py-2 rounded-lg",
                      on
                        ? "bg-paper-raised text-ink font-medium shadow-sm"
                        : "bg-transparent text-ink-muted font-normal",
                    )}
                  >
                    {t.label}{" "}
                    <span
                      className={cn(
                        "text-data-sm",
                        on ? "text-accent-ink" : "text-ink-faint",
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
              <div className="text-body-md text-ink-muted">No papers in this view yet.</div>
            ) : (
              filtered.map((p) => (
                <PaperCard key={p.id} paper={p} onOpen={() => setSelectedPaperId(p.id)} />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
