/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useRef, type ChangeEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { useSchemes, useUploadScheme } from "@/lib/hooks/useTeacherApi"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
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
  parsed: "bg-ok-wash text-ok",
  pending: "bg-accent-wash text-accent-ink",
  custom: "bg-paper-sunk text-ink-muted",
}

export function MarkSchemes() {
  const schemesQuery = useSchemes()
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

  return (
    <div className="flex flex-col gap-5">
      <QueryState
        query={schemesQuery}
        srHeading="Mark schemes"
        // Reused verbatim from the pre-conversion branch — no page-header
        // skeleton existed before this, and adding one is a layout change
        // this pending/error/empty sweep does not make.
        skeleton={<ListSkeleton rows={5} />}
        // The pre-conversion branch here was one of the plain, un-retryable
        // error lines the PR3 brief calls out: `text-accent-ink` (not even
        // the amber/neutral failure tone DESIGN.md asks for) with no retry
        // action at all. `QueryState` gives this a real `ErrorState` with a
        // `refetch`-backed retry for free.
        error={{ heading: "Couldn't load mark schemes", body: teacherLoadFailureMessage }}
      >
        {({ schemes, stats }) => (
          <>
            <div className="flex items-end gap-[18px] pb-[18px] border-b border-rule flex-wrap gap-y-2.5">
              <div>
                <div className="text-eyebrow text-ink-faint">
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
                data-kit-field="file"
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
              <div className="text-body-md text-accent-ink">
                Couldn't parse that mark scheme: {teacherMutationFailureMessage(uploadScheme.error)}
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

            <Table density="operate"
              tabIndex={0}
              role="region"
              aria-label="Uploaded mark schemes, scrollable horizontally"
            >
              <caption className="sr-only">Uploaded mark schemes</caption>
              <THead>
                <TR>
                  <TH>Document</TH>
                  <TH>Paper</TH>
                  <TH>Session</TH>
                  <TH numeric>Marks</TH>
                  <TH numeric>Questions</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {schemes.map((m) => (
                  <TR key={m.doc}>
                    <TD className="min-w-0 max-w-[280px] overflow-hidden text-ellipsis whitespace-nowrap text-data-sm">
                      {m.doc}
                    </TD>
                    <TD className="text-body-md text-ink-muted">{m.paper}</TD>
                    <TD className="text-body-md text-ink-muted">{m.session}</TD>
                    <TD numeric className="text-data-sm">
                      {m.maxMarks ?? "-"}
                    </TD>
                    <TD numeric className="text-data-sm text-ink-faint">
                      {m.questionCount ?? "-"}
                    </TD>
                    <TD>
                      <span
                        className={cn(
                          "text-body-sm rounded-full px-[11px] py-[3px]",
                          STATUS_CHIP[m.status],
                        )}
                      >
                        {m.status}
                      </span>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </>
        )}
      </QueryState>
    </div>
  )
}
