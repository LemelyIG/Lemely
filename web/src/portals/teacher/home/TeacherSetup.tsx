import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Check, Plus, UploadSimple } from "@phosphor-icons/react"
import type { ClassSummary } from "@/lib/teacherTypes"
import type { SetupProgress } from "./setup"
import "./home.css"

const STEPS = [
  { key: "created", title: "Create a class", what: "Get a join code to share with your students." },
  { key: "uploaded", title: "Upload papers", what: "A whole class set at once, as PDFs." },
  { key: "reviewed", title: "Review flagged answers", what: "Check the answers Lemely is unsure about." },
] as const

const isPdf = (f: File) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)

export function TeacherSetup({ progress, firstClass, onFiles }: { progress: SetupProgress; firstClass: ClassSummary | null; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [nudge, setNudge] = useState(0)
  const [copied, setCopied] = useState(false)
  const current = STEPS.findIndex((s) => !progress[s.key])

  const upload = (list: FileList | File[] | null) => {
    const pdfs = [...(list ?? [])].filter(isPdf)
    if (!pdfs.length) return
    if (!progress.created) { setNudge((n) => n + 1); return }
    onFiles(pdfs)
  }

  useEffect(() => {
    const over = (e: DragEvent) => e.preventDefault()
    const drop = (e: DragEvent) => { e.preventDefault(); upload(e.dataTransfer?.files ?? null) }
    window.addEventListener("dragover", over)
    window.addEventListener("drop", drop)
    return () => { window.removeEventListener("dragover", over); window.removeEventListener("drop", drop) }
  })

  const copy = async (code: string) => {
    try { await navigator.clipboard.writeText(code) } catch { /* clipboard blocked: the code is still visible */ }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="grid gap-8">
      <header className="rounded-card bg-inverse-surface p-8 text-inverse-on-surface">
        <p className="text-eyebrow text-inverse-primary">Every mark, explained.</p>
        <h1 className="mt-2 font-display text-[40px] font-extrabold leading-[1.05] tracking-[-0.03em]">Mark your first class set</h1>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/teacher/first-class" className="inline-flex items-center gap-2 rounded-button bg-inverse-primary px-5 py-3 btn-text text-primary">Create a class</Link>
          <button type="button" onClick={() => (progress.created ? input.current?.click() : setNudge((n) => n + 1))}
            className="rounded-button border border-inverse-on-surface/40 px-5 py-3 btn-text">Upload papers</button>
        </div>
      </header>

      <section aria-labelledby="gs-h">
        <div className="flex items-baseline justify-between">
          <h2 id="gs-h" className="text-display-xs">Get started</h2>
          <span aria-live="polite" className="text-data-md text-on-surface-variant">{progress.complete ? "All set" : `${progress.done} of 3 done`}</span>
        </div>
        <div aria-hidden className="mt-3 h-2 overflow-hidden rounded-bar bg-surface-container-high">
          <i className="block h-full origin-left bg-primary transition-transform duration-350 ease-expo" style={{ transform: `scaleX(${progress.done / 3})` }} />
        </div>
        <ol className="mt-4 grid gap-3">
          {STEPS.map((s, i) => {
            const done = progress[s.key]
            const now = i === current
            return (
              <li key={now ? `${s.key}-${nudge}` : s.key}
                className={`flex gap-4 rounded-tile p-5 ${now ? "bg-surface-container-lowest shadow-panel" : "bg-surface-container-low"} ${now && nudge ? "animate-[em-nudge_400ms_var(--ease-expo)] motion-reduce:animate-none" : ""}`}>
                <span className={`grid size-8 shrink-0 place-items-center rounded-pill font-bold ${done ? "bg-primary text-on-primary" : now ? "bg-primary-container text-on-primary-container" : "bg-surface-container-high text-on-surface-variant"}`}>
                  {done ? <Check size={16} weight="bold" aria-label="Done" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="font-bold">{s.title}</h3>
                  {s.key === "created" && done && firstClass?.joinCode ? (
                    <p className="text-body-sm text-on-surface-variant">
                      {firstClass.label} · join code <code className="text-data-md text-on-surface">{firstClass.joinCode}</code>{" "}
                      <button type="button" onClick={() => void copy(firstClass.joinCode!)} className="font-bold text-primary">{copied ? "Copied" : "Copy"}</button>
                    </p>
                  ) : (
                    <p className="text-body-sm text-on-surface-variant">{s.what}</p>
                  )}
                  {now && s.key === "created" && (
                    <Link to="/teacher/first-class" className="mt-3 inline-flex items-center gap-2 rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover"><Plus size={16} />Create a class</Link>
                  )}
                  {now && s.key === "uploaded" && (
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <button type="button" onClick={() => input.current?.click()} className="inline-flex items-center gap-2 rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover"><UploadSimple size={16} />Upload papers</button>
                      <span className="text-body-sm text-on-surface-variant">or drop them anywhere on this page</span>
                    </div>
                  )}
                  {now && s.key === "reviewed" && (
                    <Link to="/teacher/review" className="mt-3 inline-flex rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover">Open review queue</Link>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </section>
      <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
    </div>
  )
}
