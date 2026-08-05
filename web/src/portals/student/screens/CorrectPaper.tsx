import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ProcessingState, type ProcessingStage } from "@/components/ui/processing-state"
import { CameraCapture } from "@/components/CameraCapture"
import { runCorrection, uploadScan } from "@/lib/hooks/useStudentApi"
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
        return `Marked - ${frame.awarded ?? "?"}/${frame.max_marks ?? "?"}`
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

/** Move a stage to active (or done, on completion), and mark every earlier
 * pending stage done too — forward progress on stage N implies stage N-1
 * finished, since the pipeline runs in this fixed order. */
function advanceStage(
  stages: ProcessingStage[],
  id: StageId,
  detail: string | undefined,
  complete: boolean,
): ProcessingStage[] {
  const idx = STAGE_ORDER.indexOf(id)
  return stages.map((s, i) => {
    if (i < idx) return s.status === "pending" ? { ...s, status: "done" } : s
    if (i === idx) return { ...s, status: complete ? "done" : "active", detail: detail ?? s.detail }
    return s
  })
}

/** Frame chatter that isn't stage-specific (gemini calls, budget notices)
 * updates whichever stage is currently active, rather than being dropped. */
function annotateActiveStage(stages: ProcessingStage[], detail: string): ProcessingStage[] {
  const activeIdx = stages.findIndex((s) => s.status === "active")
  if (activeIdx === -1) return stages
  return stages.map((s, i) => (i === activeIdx ? { ...s, detail } : s))
}

/** Fail whichever stage is running (or the first stage, if nothing had
 * started yet — e.g. the initial upload itself failed). */
function failActiveStage(stages: ProcessingStage[], errorMessage: string): ProcessingStage[] {
  const idx = stages.findIndex((s) => s.status === "active" || s.status === "pending")
  if (idx === -1) return stages
  return stages.map((s, i) => (i === idx ? { ...s, status: "error", errorMessage } : s))
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

  const chooseScanSource = (source: ScanSource) => {
    if (source === scanSource) return
    setScanSource(source)
    setScanFile(null)
    if (source === "camera") setCameraSessionKey((k) => k + 1)
  }

  const runPipeline = async () => {
    if (!scanFile || running) return
    setRunning(true)
    setError(null)
    setStages(initialStages)
    try {
      const { paperId } = await uploadScan(scanFile, schemeFile ?? undefined)
      for await (const frame of runCorrection(paperId)) {
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
          setStages((prev) => advanceStage(prev, stageId, describeFrame(frame), isComplete))
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
          navigate(`/student/result/${paperId}`, { state: assembled })
          return
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setStages((prev) => failActiveStage(prev, message))
      setError(message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="lm-screen flex flex-col gap-container-mobile">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <h1 className="text-display-lg text-t1">
            Correct a paper
          </h1>
          <div className="text-sm text-t2 mt-[7px] max-w-[60ch] text-pretty">
            Scan or drop the paper. Lemely reads page one, identifies the exam,
            fetches the official mark scheme, and marks it.
          </div>
        </div>
        <div className="flex-1" />
        <Button
          variant="accent"
          size="lg"
          onClick={runPipeline}
          disabled={running || !scanFile}
        >
          {running ? "Marking..." : "Mark this paper"}
        </Button>
      </div>

      <div className="lm-cols grid grid-cols-[1.5fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          <Card className="p-container-mobile flex flex-col gap-5">
            <div>
              <div id="scan-label" className="text-sm font-medium block mb-1.5">
                Scanned paper <span className="text-t3 font-normal">(required)</span>
              </div>
              <div
                role="group"
                aria-label="Scan source"
                className="inline-flex rounded-md border border-border p-0.5 bg-surface-2 mb-3"
              >
                <button
                  type="button"
                  onClick={() => chooseScanSource("file")}
                  disabled={running}
                  aria-pressed={scanSource === "file"}
                  className={`text-xs font-medium rounded px-3 py-1.5 cursor-pointer transition-colors disabled:cursor-not-allowed ${
                    scanSource === "file"
                      ? "bg-surface text-t1 shadow-sm"
                      : "text-t2 hover:text-t1"
                  }`}
                >
                  Upload a file
                </button>
                <button
                  type="button"
                  onClick={() => chooseScanSource("camera")}
                  disabled={running}
                  aria-pressed={scanSource === "camera"}
                  className={`text-xs font-medium rounded px-3 py-1.5 cursor-pointer transition-colors disabled:cursor-not-allowed ${
                    scanSource === "camera"
                      ? "bg-surface text-t1 shadow-sm"
                      : "text-t2 hover:text-t1"
                  }`}
                >
                  Scan with camera
                </button>
              </div>

              {scanSource === "file" ? (
                <input
                  id="scan-file"
                  aria-labelledby="scan-label"
                  type="file"
                  accept="application/pdf,image/*"
                  disabled={running}
                  onChange={(e) => setScanFile(e.target.files?.[0] ?? null)}
                  className="text-xs text-t2 file:mr-3 file:border file:border-border file:bg-surface-2 file:rounded-lg file:px-3 file:py-1.5 file:text-xs file:cursor-pointer file:font-sans"
                />
              ) : running ? (
                <div className="text-xs text-t3">
                  {scanFile
                    ? `Scanned paper ready (${scanFile.name}).`
                    : "Marking in progress."}
                </div>
              ) : scanFile ? (
                <div className="flex items-center gap-3">
                  <div className="text-xs text-t2">
                    Scan ready - {scanFile.name}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setScanFile(null)
                      setCameraSessionKey((k) => k + 1)
                    }}
                  >
                    Rescan
                  </Button>
                </div>
              ) : (
                <CameraCapture
                  key={cameraSessionKey}
                  onComplete={(file) => setScanFile(file)}
                  onCancel={() => chooseScanSource("file")}
                  className="p-0 border-0 bg-transparent"
                />
              )}
            </div>
            <div>
              <label
                htmlFor="scheme-file"
                className="text-sm font-medium block mb-1.5"
              >
                Mark scheme (optional)
              </label>
              <input
                id="scheme-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={running}
                onChange={(e) => setSchemeFile(e.target.files?.[0] ?? null)}
                className="text-xs text-t2 file:mr-3 file:border file:border-border file:bg-surface-2 file:rounded-lg file:px-3 file:py-1.5 file:text-xs file:cursor-pointer file:font-sans"
              />
              <div className="text-xs text-t3 mt-1.5">
                Leave this blank and Lemely fetches the official scheme once it
                identifies the exam.
              </div>
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card className="p-5">
            <div role="status" className="flex items-center gap-[9px] mb-4">
              <span
                aria-hidden="true"
                className={`w-[7px] h-[7px] rounded-full animate-[lm-pulse_1.6s_infinite] ${running ? "bg-accent" : error ? "bg-warn" : "bg-ok"}`}
              />
              <div className="text-body-lg font-semibold">
                {running ? "Marking now" : error ? "Marking stopped" : "Ready when you are"}
              </div>
            </div>
            <ProcessingState stages={stages} />
          </Card>

          <Card className="p-5">
            <div className="text-body-lg font-semibold mb-[5px]">
              How this gets marked
            </div>
            <div className="text-sm text-t2 mb-[15px]">
              Worth knowing before you trust the number
            </div>
            <div className="flex flex-col gap-[13px]">
              {reassure.map((r, i) => (
                <div key={i} className="flex gap-[11px] items-start">
                  <span className="w-[5px] h-[5px] rounded-full bg-accent mt-[7px] flex-none" />
                  <span className="text-sm leading-[1.5] text-t2 text-pretty">
                    {r.t}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
