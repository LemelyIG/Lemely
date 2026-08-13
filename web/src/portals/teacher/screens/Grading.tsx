import { useState, type ChangeEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { ProcessingState, type ProcessingStage } from "@/components/ui/processing-state"
import { cn } from "@/lib/utils"
import { failActiveStage } from "@/lib/pipelineStages"
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
  graded: "bg-ok-bg text-ok",
  review: "bg-err-bg text-err",
  processing: "bg-accent-subtle text-accent-subtle-on",
  queued: "bg-surface-2 text-t2",
  // Distinct from `review`'s red: review means "a human should look at these
  // marks", failed means "there are no marks". Reading as the same state would
  // send a teacher hunting for a score that was never produced.
  failed: "bg-surface-2 text-err border border-err",
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
  const previewUrl = useScanPreview(paper.id)
  const showSpinner = paper.kind === "processing"
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
          <div className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-err text-accent-on text-3xs flex items-center justify-center font-mono">
            !
          </div>
        ) : null}
        {showSpinner ? (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-2/70">
            <div className="w-[26px] h-[26px] rounded-full border-[3px] border-border border-t-accent animate-spin" />
          </div>
        ) : null}
      </div>
      <div className="px-[13px] py-3">
        <div className="flex items-center gap-2">
          {/* `min-w-0` + `truncate`: a flex child's default `min-width: auto`
              refuses to shrink below its content, so a long name (the detected
              label is longer still — "Paper 1 V2 May/June 2020 - 2026-08-12")
              pushed the status chip off the card's right edge and clipped it. */}
          <div className="text-dense-lg font-medium flex-1 min-w-0 truncate" title={paper.name}>
            {paper.name}
          </div>
          <div
            className={cn(
              "text-3xs rounded-full px-[9px] py-0.5 whitespace-nowrap flex-none",
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
            {!activePaperId ? (
              <div className="text-dense text-t2 mt-[18px]">
                Upload a scan to see detected fields.
              </div>
            ) : detectedFields.length === 0 ? (
              // Detection is the first phase of the server-side run, so an
              // in-flight paper genuinely has no answer yet — say which of the
              // two it is rather than reporting "none" for both.
              <div className="text-dense text-t2 mt-[18px]">
                {detail && (detail.kind === "queued" || detail.kind === "processing")
                  ? "Reading this scan's exam details…"
                  : "No metadata detected for this paper."}
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
            {!activePaperId ? (
              <div className="text-dense text-t2">Upload a scan to see its pipeline.</div>
            ) : paperDetailQuery.isPending ? (
              <div className="text-dense text-t2">Loading…</div>
            ) : paperDetailQuery.isError ? (
              <div className="text-dense text-accent">
                Couldn't load pipeline: {paperDetailQuery.error.message}
              </div>
            ) : detail ? (
              <>
                {detail.pipeline.map((p) => (
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
                ))}
                {detail.kind === "queued" ? (
                  <div className="text-dense text-t2 mt-2">
                    Waiting for the marking worker.
                  </div>
                ) : null}
                {detail.error ? (
                  // The specific reason, from the server — never a generic
                  // "something went wrong". A paper that produced no marks has
                  // to say why, or the teacher has nothing to act on.
                  <div className="mt-3 pt-3 border-t border-border flex flex-col gap-2.5 items-start">
                    <div className="text-dense text-err">{detail.error}</div>
                    <Button
                      variant="ink"
                      size="sm"
                      disabled={regrade.isPending}
                      onClick={() => regrade.mutate(detail.id)}
                    >
                      {regrade.isPending ? "Queueing…" : "Try again"}
                    </Button>
                    {regrade.isError ? (
                      <div className="text-dense text-err">
                        Couldn't re-queue: {regrade.error.message}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
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
                <ProcessingState stages={stages} className="border-t border-border pt-4" />
                {stages.every((s) => s.status === "done") ? (
                  <div className="text-dense text-t2">
                    Marking runs on the server — it keeps going if you close this
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
                <PaperCard key={p.id} paper={p} onOpen={() => setSelectedPaperId(p.id)} />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
