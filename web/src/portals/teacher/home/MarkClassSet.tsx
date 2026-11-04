import { useRef, useState } from "react"
import { Check, UploadSimple } from "@phosphor-icons/react"
import "./home.css"

const isPdf = (f: File) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)

export function MarkClassSet({ lastUpload, onFiles }: { lastUpload: string | null; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [received, setReceived] = useState(false)
  const take = (list: FileList | null) => {
    const pdfs = [...(list ?? [])].filter(isPdf)
    if (!pdfs.length) return
    setReceived(true)
    window.setTimeout(() => onFiles(pdfs), 600)
  }
  return (
    <section
      aria-labelledby="mcs-h"
      className={`relative rounded-card bg-surface-container-lowest p-6 shadow-panel ${received ? "th-received" : ""}`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); take(e.dataTransfer.files) }}
    >
      <div className="flex items-baseline justify-between">
        <h2 id="mcs-h" className="text-eyebrow text-on-surface-variant">Mark a class set</h2>
        {received ? (
          <span className="th-got inline-flex items-center gap-1 text-data-md text-success-text"><Check size={14} weight="bold" />Received</span>
        ) : (
          lastUpload && <small className="text-body-sm text-on-surface-variant">Last: {lastUpload}</small>
        )}
      </div>
      <div className="mt-4 grid place-items-center gap-3 rounded-tile border border-dashed border-outline p-8 text-center">
        <span aria-hidden className="grid size-11 place-items-center rounded-chip bg-primary-container text-on-primary-container"><UploadSimple size={20} /></span>
        <p className="text-display-xs">Drop papers anywhere on this page</p>
        <p className="max-w-[44ch] text-body-sm text-on-surface-variant">One PDF per student. Lemely reads each student's name off the paper.</p>
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="inline-flex items-center gap-2 rounded-button bg-primary px-5 py-3 btn-text text-on-primary hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          <UploadSimple size={16} />Upload papers
        </button>
        <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => take(e.target.files)} />
      </div>
      <span aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center">
        <svg className="th-big size-24 opacity-0" viewBox="0 0 24 24" fill="none" stroke="var(--md-success)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
      </span>
    </section>
  )
}
