/* Past papers screen and sheet (L4): the decisions their `.tsx` files only wire. Pure; no `.tsx` imports. */
import type { QueryStateQuery } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import type { PastPaper, PastPapers } from "@/lib/practiceHubTypes"
import type { CreatePracticeResponse } from "@/lib/practiceTypes"
import type { PaperOption, PaperSheetView } from "./papersModel"

type Status = "pending" | "error" | "success"

export type SubjectsGate = "loading" | "error" | "none" | "ready"

/**
 * What the page can show before a subject is known. Any known subject is enough
 * to start, so a failed or slow source never hides a list that can already load.
 * With none known, a source still loading wins over one that failed (it may yet
 * bring subjects), and "none" is only said once both answered and found nothing.
 */
export function subjectsGate(input: { overviewStatus: Status; profileStatus: Status; subjectCount: number }): SubjectsGate {
  if (input.subjectCount > 0) return "ready"
  if (input.overviewStatus === "pending" || input.profileStatus === "pending") return "loading"
  if (input.overviewStatus === "error" || input.profileStatus === "error") return "error"
  return "none"
}

/** The subject the list is for: the student's pick, else the first. Empty when there is none. */
export function resolvePapersSubject(
  subjects: readonly { code: string; name: string }[],
  chosen: string | null,
): { code: string; name: string } {
  const found = chosen ? subjects.find((s) => s.code === chosen) : undefined
  const subject = found ?? subjects[0]
  return subject ? { code: subject.code, name: subject.name } : { code: "", name: "" }
}

export type PapersQuery = QueryStateQuery<PastPapers>

/**
 * `QueryState` treats an `error` status as a failure and drops the data. A
 * failed refresh behind a list already loaded is not that: the list is still
 * true, so it stays and the screen says the refresh failed. Only an error with
 * nothing cached is a real error.
 */
export function gatePapersQuery(query: PapersQuery): { query: PapersQuery; refreshFailed: boolean } {
  if (query.status === "error" && query.data !== undefined) {
    return { query: { ...query, status: "success" }, refreshFailed: true }
  }
  return { query, refreshFailed: false }
}

export function noSubjectsCopy(): { heading: string; body: string } {
  return { heading: "No subjects yet", body: "Add a subject and its past papers show up here." }
}

/** A choice the sheet no longer offers (no clock on this paper) falls back to its default. */
export function effectiveOption(view: PaperSheetView, choice: PaperOption): PaperOption {
  return view.options.some((o) => o.key === choice) ? choice : view.defaultOption
}

export interface PrintFailure {
  message: string
  retryable: boolean
}

/** Said up front for a paper with no questions, and after the server's 409 for one that lost them. */
export const NOT_PRINTABLE = "We can’t print this one yet."

/** 409 means the paper has nothing servable to print; another attempt cannot change that. */
export function printFailure(error: unknown): PrintFailure {
  if (error instanceof ApiError && error.status === 409) return { message: NOT_PRINTABLE, retryable: false }
  return { message: "Couldn’t get this paper ready. Try again.", retryable: true }
}

export function printPath(assignmentId: string): string {
  return `/student/practice/print/${assignmentId}`
}

/** While the paper is being made the sheet stays, so the navigation never lands from a closed sheet. */
export function canDismissSheet(pending: boolean): boolean {
  return !pending
}

/** What the sheet lends `runPrint`: the mutation and the router. */
export interface PrintIo {
  mutate: (args: { paperId: string; timed: boolean }) => Promise<CreatePracticeResponse>
  navigate: (to: string) => void
}

export type PrintOutcome = { kind: "created"; to: string } | { kind: "failed"; failure: PrintFailure } | { kind: "blocked" }

/** One attempt to print: make the paper's set, then open its print view. Never throws. */
export async function runPrint(io: PrintIo, paper: PastPaper, view: PaperSheetView, choice: PaperOption): Promise<PrintOutcome> {
  if (!view.printable) return { kind: "blocked" }
  try {
    const created = await io.mutate({ paperId: paper.paperId, timed: effectiveOption(view, choice) === "timed" })
    const to = printPath(created.assignmentId)
    io.navigate(to)
    return { kind: "created", to }
  } catch (error) {
    return { kind: "failed", failure: printFailure(error) }
  }
}
