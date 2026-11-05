/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V4 */
import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { UploadSimple } from "@phosphor-icons/react"
import { prefersReducedMotion } from "@/lib/celebration"
import "./home.css"

const isPdf = (f: File) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)
const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files")
const size = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)
/** Long enough for the big tick and the Received chip (1.05s + 0.6s) to finish before the hand-off. */
const HANDOFF_MS = 1700

type State = "idle" | "queued"

/** Mark card, ported from the approved prototype: page-wide drop, a big tick, then the hand-off. */
export function MarkClassSet({ lastUpload, onFiles }: { lastUpload: string | null; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const card = useRef<HTMLElement>(null)
  const [state, setState] = useState<State>("idle")
  const [dragging, setDragging] = useState(false)
  const [queued, setQueued] = useState<File[]>([])
  const [note, setNote] = useState("")
  const timer = useRef<number | null>(null)
  const onFilesRef = useRef(onFiles)
  onFilesRef.current = onFiles
  const pending = useRef<File[]>([])
  const raf = useRef<number | null>(null)
  const clear = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null }
    if (raf.current !== null) { window.cancelAnimationFrame(raf.current); raf.current = null }
  }
  const flush = () => {
    const files = pending.current
    pending.current = []
    if (files.length) onFilesRef.current(files)
  }
  const take = (list: FileList | File[] | null) => {
    const all = [...(list ?? [])]
    const pdfs = all.filter(isPdf)
    const skipped = all.length - pdfs.length
    if (!pdfs.length) {
      if (skipped && !pending.current.length) setNote("Only PDFs can be marked. Nothing was added.")
      return
    }
    setNote(skipped ? `${skipped} not a PDF, skipped.` : "")
    // Every batch inside the window is kept: append, then re-arm the one timer.
    pending.current = [...pending.current, ...pdfs]
    clear()
    if (prefersReducedMotion()) { flush(); return }
    setQueued(pending.current)
    // Back to idle, then queued on the next frame, so a later drop replays the big tick.
    setState("idle")
    raf.current = window.requestAnimationFrame(() => { raf.current = null; setState("queued") })
    timer.current = window.setTimeout(() => {
      timer.current = null
      setState("idle")
      flush()
    }, HANDOFF_MS)
  }
  const takeRef = useRef(take)
  takeRef.current = take
  useEffect(() => {
    // Page-wide drag and drop. Depth counts nested enter/leave pairs so the veil does not flicker.
    let depth = 0
    const enter = (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; setDragging(true) }
    const over = (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "copy" }
    const leave = (e: DragEvent) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) setDragging(false) }
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth = 0
      setDragging(false)
      takeRef.current(e.dataTransfer?.files ?? null)
      card.current?.scrollIntoView?.({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" })
    }
    window.addEventListener("dragenter", enter)
    window.addEventListener("dragover", over)
    window.addEventListener("dragleave", leave)
    window.addEventListener("drop", drop)
    return () => {
      window.removeEventListener("dragenter", enter)
      window.removeEventListener("dragover", over)
      window.removeEventListener("dragleave", leave)
      window.removeEventListener("drop", drop)
      clear()
    }
    // Leaving the page within the hand-off window cancels the pending hand-over (intended).
  }, [])
  const count = queued.length
  return (
    <section
      ref={card}
      aria-labelledby="mcs-h"
      data-state={state}
      className="th-mark th-lift relative flex min-w-0 flex-col gap-3 rounded-tile bg-surface-container-lowest p-3.5"
    >
      <header className="flex items-baseline justify-between gap-3 px-1 pt-0.5">
        <h2 id="mcs-h" className="text-eyebrow text-on-surface-variant">Mark papers</h2>
        {state === "queued" ? (
          <span className="th-got items-center gap-1 rounded-pill bg-primary py-[3px] pr-2.5 pl-1.5 text-label-sm text-on-primary">
            <svg aria-hidden viewBox="0 0 24 24" className="size-[15px]" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
            Received
          </span>
        ) : (
          lastUpload && <small className="text-body-sm text-on-surface-variant">Last: {lastUpload}</small>
        )}
      </header>
      {state === "queued" ? (
        <div className="th-batch flex flex-col gap-2.5">
          <p className="th-h text-display-xs">{count} {count === 1 ? "paper" : "papers"} ready</p>
          <ul className="th-files max-h-[132px] overflow-y-auto rounded-chip bg-surface-container-low">
            {queued.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex justify-between gap-3 border-t border-outline-variant px-3 py-[7px] text-metadata first:border-t-0">
                <span className="min-w-0 truncate">{f.name}</span>
                <small className="text-on-surface-variant">{size(f.size)}</small>
              </li>
            ))}
          </ul>
          {note && <p className="text-body-sm text-on-surface-variant">{note}</p>}
          <p className="text-body-sm text-on-surface-variant">Opening marking. Each paper is marked one at a time.</p>
        </div>
      ) : (
        <div data-over={dragging || undefined} className="th-zone grid flex-1 place-content-center justify-items-center gap-1.5 rounded-inner px-4 py-[22px] text-center">
          <span aria-hidden className="th-ic mb-1 grid size-11 place-items-center rounded-button bg-secondary-container text-primary"><UploadSimple size={18} /></span>
          <p className="th-h text-display-xs">Drop papers anywhere on this page</p>
          <p className="max-w-[40ch] text-body-sm text-on-surface-variant">One PDF per student, marked one at a time. Lemely reads the student's name off the paper.</p>
          {note && <p className="max-w-[40ch] text-body-sm text-on-surface-variant">{note}</p>}
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="th-btn mt-2 transition-colors inline-flex h-9 items-center gap-[7px] rounded-chip bg-primary px-3.5 btn-text text-on-primary hover:bg-primary-hover"
          >
            <UploadSimple size={18} />Upload papers
          </button>
        </div>
      )}
      <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => { take(e.target.files); e.target.value = "" }} />
      <span role="status" className="sr-only">{state === "queued" ? `${count} ${count === 1 ? "paper" : "papers"} received. Opening marking.` : note}</span>
      <span aria-hidden className="th-fx">
        <span className="th-big"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
      </span>
      {dragging && typeof document !== "undefined" && createPortal(
        <div aria-hidden className="th-dropveil rounded-board">
          <b className="text-display-md">Drop to start marking</b>
          <span className="text-body-sm">One PDF per student</span>
        </div>,
        document.body,
      )}
    </section>
  )
}
