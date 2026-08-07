import { useRef, type ChangeEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { useSchemes, useUploadScheme } from "@/lib/hooks/useTeacherApi"
import type { SchemeStatus } from "@/lib/teacherTypes"

/*
 * Mark schemes. Wired to `GET /schemes` via `useSchemes()`, upload via
 * `useUploadScheme()`.
 *
 * Cuts made vs. the mock (see `SchemeListDTO` in `lib/teacherTypes.ts` /
 * `lemely/web/routers/teacher.py::list_schemes`):
 *  - `stats` renders whatever the API returns (currently always 2 cards,
 *    "Parsed"/"Failed") instead of the mock's hardcoded 4-card grid — the
 *    router dropped "Pending"/"Your own" because no upload-queue or
 *    per-teacher scheme-ownership model exists yet.
 *  - The header's "214 documents" count is replaced with the live
 *    `schemes.length`.
 *  - "Parse 6 pending" button dropped entirely — no upload-queue concept to
 *    back it.
 *  - "Upload your own" now triggers a real (hidden) file input and calls
 *    `useUploadScheme()`; on success the schemes list is invalidated so the
 *    new row appears, on a 422 parse failure the error surfaces inline.
 */

const STATUS_CHIP: Record<SchemeStatus, string> = {
  parsed: "bg-ok-bg text-ok",
  pending: "bg-accent-subtle text-accent-subtle-on",
  custom: "bg-surface-2 text-t2",
}

const COLS = "grid grid-cols-[minmax(0,1.6fr)_84px_104px_62px_74px_92px] gap-[14px]"

export function MarkSchemes() {
  const { data, isPending, isError, error } = useSchemes()
  const uploadScheme = useUploadScheme()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    uploadScheme.mutate(file, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["teacher", "schemes"] })
      },
    })
  }

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-dense-lg text-t2">Loading mark schemes…</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-dense-lg text-accent">
          Couldn't load mark schemes: {error.message}
        </div>
      </div>
    )
  }

  const { schemes, stats } = data

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-2xs tracking-[0.11em] uppercase text-t3">
            Library · {schemes.length} scheme{schemes.length === 1 ? "" : "s"}
          </div>
          {/* A real h1, not a styled div — same `page-has-heading-one`
              violation as Grading.tsx, surfaced by the same chunk-b
              registry expansion. */}
          <h1 className="text-display-md mt-1.5">
            Mark schemes
          </h1>
        </div>
        <div className="flex-1" />
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={handleFileChange}
        />
        <Button
          variant="secondary"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadScheme.isPending}
        >
          {uploadScheme.isPending ? "Uploading…" : "Upload your own"}
        </Button>
      </div>

      {uploadScheme.isError ? (
        <div className="text-dense text-accent">
          Couldn't parse that mark scheme: {uploadScheme.error.message}
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {stats.map((s) => (
          <StatCard
            key={s.key}
            stat={{
              k: s.key,
              v: s.value,
              unit: s.unit ?? undefined,
              foot: s.foot ?? undefined,
              valueTone: s.valueTone,
              footTone: s.footTone,
            }}
          />
        ))}
      </div>

      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div
          className={cn(
            COLS,
            "px-[22px] py-2.5 bg-surface-2 border-b border-border font-mono text-3xs tracking-[0.09em] uppercase text-t3",
          )}
        >
          <div>Document</div>
          <div>Paper</div>
          <div>Session</div>
          <div>Marks</div>
          <div>Questions</div>
          <div>Status</div>
        </div>
        {schemes.map((m) => (
          <div
            key={m.doc}
            className={cn(
              COLS,
              "items-center px-[22px] py-[13px] border-b border-border",
            )}
          >
            <div className="font-mono text-dense-sm min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
              {m.doc}
            </div>
            <div className="text-dense text-t2">{m.paper}</div>
            <div className="text-dense text-t2">{m.session}</div>
            <div className="font-mono text-dense-sm">{m.maxMarks ?? "-"}</div>
            <div className="font-mono text-dense-sm text-t2">{m.questionCount ?? "-"}</div>
            <div>
              <span
                className={cn(
                  "text-xs rounded-full px-[11px] py-[3px]",
                  STATUS_CHIP[m.status],
                )}
              >
                {m.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
