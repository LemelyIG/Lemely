import { useState, type ChangeEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ApiError } from "@/lib/api"
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
 *    upload -> grade and streams progress into a small log.
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
  graded: "bg-ok-bg text-[oklch(0.36_0.09_152)]",
  review: "bg-err-bg text-[oklch(0.40_0.10_22)]",
  processing: "bg-accent-subtle text-[oklch(0.42_0.10_68)]",
  queued: "bg-[oklch(0.93_0.008_78)] text-t2",
}

type TabId = "all" | "review" | "graded" | "processing"

function filterPapers(papers: PaperSummary[], tab: TabId): PaperSummary[] {
  if (tab === "all") return papers
  if (tab === "processing") {
    return papers.filter((p) => p.kind === "processing" || p.kind === "queued")
  }
  return papers.filter((p) => p.kind === tab)
}

/** Human label for one SSE frame, appended to the running log as it arrives. */
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
        "rounded-[13px] overflow-hidden bg-surface cursor-pointer transition-transform hover:-translate-y-0.5 border",
        paper.kind === "review" ? "border-[oklch(0.84_0.06_22)]" : "border-border",
      )}
    >
      <div className="relative h-[64px] bg-[oklch(0.975_0.008_78)] border-b border-border overflow-hidden">
        {paper.kind === "review" ? (
          <div className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-err text-accent-on text-[10px] flex items-center justify-center font-mono">
            !
          </div>
        ) : null}
        {showSpinner ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-[26px] h-[26px] rounded-full border-[3px] border-[oklch(0.90_0.012_78)] border-t-accent animate-spin" />
          </div>
        ) : null}
      </div>
      <div className="px-[13px] py-3">
        <div className="flex items-center gap-2">
          <div className="text-[13.5px] font-medium flex-1">{paper.name}</div>
          <div
            className={cn(
              "text-[10.5px] rounded-full px-[9px] py-0.5",
              CHIP_TONE[paper.kind],
            )}
          >
            {paper.status}
          </div>
        </div>
        <div className="flex items-baseline gap-2 mt-[9px]">
          {confText ? (
            <div className={cn("font-mono text-[11.5px]", confTone)}>{confText}</div>
          ) : null}
          <div className="flex-1" />
          <div className="font-mono text-[15px]">{scoreText}</div>
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
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [log, setLog] = useState<string[]>([])

  const papersQuery = usePapers()
  const paperDetailQuery = usePaperDetail(selectedPaperId)

  const runGrading = async (paperId: string) => {
    setGradingIds((prev) => ({ ...prev, [paperId]: true }))
    try {
      for await (const frame of gradePaper(paperId)) {
        if (frame.type === "warning" || frame.type === "error") {
          setLog((prev) => [
            ...prev,
            frame.message ?? "Something went wrong while grading this paper.",
          ])
          continue
        }
        setLog((prev) => [...prev, describeFrame(frame)])
      }
    } catch (err) {
      setLog((prev) => [...prev, err instanceof Error ? err.message : String(err)])
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
    setUploadError(null)
    setLog([])
    try {
      const { paperId, detected } = await uploadPaper(scanFile, schemeFile ?? undefined)
      setDetectedByPaper((prev) => ({ ...prev, [paperId]: detected }))
      setSelectedPaperId(paperId)
      setScanFile(null)
      setSchemeFile(null)
      queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })
      await runGrading(paperId)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err))
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
        <div className="text-[13.5px] text-t2">Loading papers…</div>
      </div>
    )
  }

  if (papersQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-[13.5px] text-accent">
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

  const isSelectedPaperNotGraded =
    paperDetailQuery.isError &&
    paperDetailQuery.error instanceof ApiError &&
    paperDetailQuery.error.status === 409

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Grading console
          </div>
          {/* A real h1, not a styled div: axe's `page-has-heading-one` fired
              on this route the moment P3.10 chunk b added it to the audit
              registry, and QUALITY-BAR.md requires one h1 per page. */}
          <h1 className="font-serif text-[34px] leading-[1.1] mt-1.5">
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
          <div className="bg-surface border border-border rounded-[14px] px-5 py-[18px]">
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
              Detected
            </div>
            {!selectedPaperId ? (
              <div className="text-[13px] text-t2 mt-[18px]">
                Upload a scan to see detected fields.
              </div>
            ) : detectedFields.length === 0 ? (
              <div className="text-[13px] text-t2 mt-[18px]">
                No metadata detected for this paper.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-x-[14px] gap-y-4 mt-[18px]">
                {detectedFields.map((d) => (
                  <div key={d.key}>
                    <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-t3">
                      {d.key}
                    </div>
                    <div className="font-mono text-[15px] mt-1">{d.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-surface border border-border rounded-[14px] p-5 flex gap-5 items-center">
            <svg
              viewBox="0 0 100 100"
              className="w-[92px] h-[92px] flex-none -rotate-90"
            >
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="oklch(0.92 0.012 78)"
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
              <div className="text-[15px] font-semibold">Auto-grading</div>
              {processingCount > 0 ? (
                <div className="font-mono text-[11.5px] text-t2 mt-[5px]">
                  {processingCount} processing
                </div>
              ) : null}
              <div className="flex gap-[22px] mt-[14px]">
                <div>
                  <div className="font-serif text-[26px] leading-none">{gradedCount}</div>
                  <div className="font-mono text-[10px] text-t3 mt-[3px]">
                    AUTO-CONFIRMED
                  </div>
                </div>
                <div>
                  <div className="font-serif text-[26px] leading-none text-err">
                    {reviewCount}
                  </div>
                  <div className="font-mono text-[10px] text-t3 mt-[3px]">
                    NEED REVIEW
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface border border-border rounded-[14px] px-5 py-[18px]">
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-[14px]">
              Pipeline
            </div>
            {!selectedPaperId ? (
              <div className="text-[13px] text-t2">Upload a scan to see its pipeline.</div>
            ) : paperDetailQuery.isPending ? (
              <div className="text-[13px] text-t2">Loading…</div>
            ) : isSelectedPaperNotGraded ? (
              <div className="text-[13px] text-t2">
                {gradingIds[selectedPaperId] ? "Grading in progress…" : "Not graded yet."}
              </div>
            ) : paperDetailQuery.isError ? (
              <div className="text-[13px] text-accent">
                Couldn't load pipeline: {paperDetailQuery.error.message}
              </div>
            ) : (
              paperDetailQuery.data.pipeline.map((p) => (
                <div key={p.label} className="flex items-center gap-3 py-[9px]">
                  <span
                    className={cn(
                      "w-[19px] h-[19px] flex-none rounded-full border-[1.5px] flex items-center justify-center text-[10px] font-mono",
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
                      "flex-1 text-[13.5px]",
                      p.state === "idle" ? "text-t3" : "text-t1",
                    )}
                  >
                    {p.label}
                  </span>
                  <span className="font-mono text-[12px] text-t2">{p.count}</span>
                </div>
              ))
            )}
          </div>

          <div className="border border-border rounded-[14px] p-5 bg-[oklch(0.975_0.01_78)] flex flex-col gap-3">
            <div className="text-[14px] font-medium">Upload a scan</div>
            <div>
              <label
                htmlFor="grading-scan-file"
                className="text-[12px] font-medium block mb-1.5"
              >
                Scanned paper
              </label>
              <input
                id="grading-scan-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleScanChange}
                className="text-[12px] text-t2 file:mr-3 file:border file:border-border file:bg-surface file:rounded-lg file:px-3 file:py-1.5 file:text-[12px] file:cursor-pointer file:font-sans"
              />
            </div>
            <div>
              <label
                htmlFor="grading-scheme-file"
                className="text-[12px] font-medium block mb-1.5"
              >
                Mark scheme (optional)
              </label>
              <input
                id="grading-scheme-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={uploading}
                onChange={handleSchemeChange}
                className="text-[12px] text-t2 file:mr-3 file:border file:border-border file:bg-surface file:rounded-lg file:px-3 file:py-1.5 file:text-[12px] file:cursor-pointer file:font-sans"
              />
              {!schemeFile ? (
                <div className="font-mono text-[10.5px] text-t3 mt-1.5">
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
              {uploading ? "Uploading…" : "Upload & grade"}
            </Button>
            {uploadError ? (
              <div className="text-[12px] text-accent">{uploadError}</div>
            ) : null}
            {log.length > 0 ? (
              <div className="flex flex-col gap-1 max-h-[140px] overflow-auto lm-scroll border-t border-border pt-2">
                {log.map((line, i) => (
                  <div key={i} className="text-[11.5px] text-t2 leading-[1.4]">
                    {line}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        {/* Right column: tabs + papers */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-[14px] flex-wrap">
            <div className="flex gap-1 bg-[oklch(0.945_0.012_78)] p-1 rounded-[11px]">
              {tabs.map((t) => {
                const on = tab === t.id
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={cn(
                      "border-0 cursor-pointer text-[13px] px-[14px] py-2 rounded-lg",
                      on
                        ? "bg-surface text-t1 font-medium shadow-[0_1px_3px_oklch(0.2_0.02_60/.08)]"
                        : "bg-transparent text-t2 font-normal",
                    )}
                  >
                    {t.label}{" "}
                    <span
                      className={cn(
                        "font-mono text-[11.5px]",
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
              <div className="text-[13px] text-t2">No papers in this view yet.</div>
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
