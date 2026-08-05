import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
 */

/** Human label for one SSE frame, appended to the running log as it arrives. */
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

export function CorrectPaper() {
  const navigate = useNavigate()
  const [scanFile, setScanFile] = useState<File | null>(null)
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<string[]>([])
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
    setLog([])
    try {
      const { paperId } = await uploadScan(scanFile, schemeFile ?? undefined)
      for await (const frame of runCorrection(paperId)) {
        if (frame.type === "warning" || frame.type === "error") {
          setError(frame.message ?? "Something went wrong while marking this paper.")
          return
        }
        setLog((prev) => [...prev, describeFrame(frame)])
        if (frame.type === "marking_progress" && frame.phase === "complete") {
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
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[36px] leading-[1.1]">
            Correct a paper
          </div>
          <div className="text-[14px] text-t2 mt-[7px] max-w-[60ch] text-pretty">
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
          <Card className="p-[22px] flex flex-col gap-5">
            <div>
              <div className="text-[13px] font-medium block mb-1.5">
                Scanned paper
              </div>
              <div className="inline-flex rounded-[10px] border border-border p-0.5 bg-surface-2 mb-3">
                <button
                  type="button"
                  onClick={() => chooseScanSource("file")}
                  disabled={running}
                  className={`text-[12.5px] font-medium rounded-[8px] px-3 py-1.5 cursor-pointer transition-colors disabled:cursor-not-allowed ${
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
                  className={`text-[12.5px] font-medium rounded-[8px] px-3 py-1.5 cursor-pointer transition-colors disabled:cursor-not-allowed ${
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
                  type="file"
                  accept="application/pdf,image/*"
                  disabled={running}
                  onChange={(e) => setScanFile(e.target.files?.[0] ?? null)}
                  className="text-[12.5px] text-t2 file:mr-3 file:border file:border-border file:bg-surface-2 file:rounded-lg file:px-3 file:py-1.5 file:text-[12.5px] file:cursor-pointer file:font-sans"
                />
              ) : running ? (
                <div className="text-[12.5px] text-t3">
                  {scanFile
                    ? `Scanned paper ready (${scanFile.name}).`
                    : "Marking in progress."}
                </div>
              ) : scanFile ? (
                <div className="flex items-center gap-3">
                  <div className="text-[12.5px] text-t2">
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
                className="text-[13px] font-medium block mb-1.5"
              >
                Mark scheme (optional)
              </label>
              <input
                id="scheme-file"
                type="file"
                accept="application/pdf,image/*"
                disabled={running}
                onChange={(e) => setSchemeFile(e.target.files?.[0] ?? null)}
                className="text-[12.5px] text-t2 file:mr-3 file:border file:border-border file:bg-surface-2 file:rounded-lg file:px-3 file:py-1.5 file:text-[12.5px] file:cursor-pointer file:font-sans"
              />
              <div className="text-[11.5px] text-t3 mt-1.5">
                Leave this blank and Lemely fetches the official scheme once it
                identifies the exam.
              </div>
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card className="p-5">
            <div className="flex items-center gap-[9px] mb-4">
              <span
                className={`w-[7px] h-[7px] rounded-full animate-[lm-pulse_1.6s_infinite] ${running ? "bg-accent" : error ? "bg-warn" : "bg-ok"}`}
              />
              <div className="text-[15px] font-semibold">
                {running ? "Marking now" : error ? "Marking stopped" : "Ready when you are"}
              </div>
            </div>
            {error ? (
              <div className="text-[12.5px] text-accent leading-[1.5] mb-3 text-pretty">
                {error}
              </div>
            ) : null}
            <div className="flex flex-col min-h-[214px] max-h-[400px] overflow-auto lm-scroll">
              {log.length === 0 ? (
                <div className="text-[12.5px] text-t3 py-[11px]">
                  Nothing yet - pick a scan and mark it to see progress here.
                </div>
              ) : (
                log.map((line, i) => (
                  <div
                    key={i}
                    className="grid grid-cols-[20px_1fr] gap-3 items-start py-[11px] border-t border-border"
                  >
                    <span className="w-[18px] h-[18px] rounded-full border-[1.5px] border-ok text-ok flex items-center justify-center mt-px">
                      <Check size={9} weight="bold" />
                    </span>
                    <span className="text-[13px] leading-[1.35]">{line}</span>
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card className="p-5">
            <div className="text-[15px] font-semibold mb-[5px]">
              How this gets marked
            </div>
            <div className="text-[12.5px] text-t2 mb-[15px]">
              Worth knowing before you trust the number
            </div>
            <div className="flex flex-col gap-[13px]">
              {reassure.map((r, i) => (
                <div key={i} className="flex gap-[11px] items-start">
                  <span className="w-[5px] h-[5px] rounded-full bg-accent mt-[7px] flex-none" />
                  <span className="text-[12.5px] leading-[1.5] text-t2 text-pretty">
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
