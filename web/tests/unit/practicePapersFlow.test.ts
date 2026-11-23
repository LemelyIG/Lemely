import { describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { PastPaper, PastPapers } from "@/lib/practiceHubTypes"
import {
  canDismissSheet,
  effectiveOption,
  gatePapersQuery,
  noSubjectsCopy,
  printFailure,
  printPath,
  resolvePapersSubject,
  runPrint,
  subjectsGate,
  type PrintIo,
} from "@/portals/student/screens/practice/papers/papersFlow"
import { paperSheetView } from "@/portals/student/screens/practice/papers/papersModel"

const paper = (over: Partial<PastPaper> = {}): PastPaper => ({
  paperId: "p1",
  code: "0580/42",
  subjectCode: "0580",
  paperNumber: 4,
  paperVariant: 2,
  sessionLabel: "May/June 2025",
  durationMinutes: 150,
  totalMarks: 80,
  questionCount: 18,
  awardedMarks: null,
  maximumMarks: null,
  ...over,
})

const SUBJECTS = [
  { code: "0580", name: "Maths" },
  { code: "0625", name: "Physics" },
]

describe("subjectsGate: what the page can show before it knows a subject", () => {
  it("is ready as soon as any subject is known, whatever else is loading or failed", () => {
    for (const overviewStatus of ["pending", "error", "success"] as const) {
      for (const profileStatus of ["pending", "error", "success"] as const) {
        expect(subjectsGate({ overviewStatus, profileStatus, subjectCount: 1 })).toBe("ready")
      }
    }
  })

  it("waits while either source is still loading and nothing is known yet", () => {
    expect(subjectsGate({ overviewStatus: "pending", profileStatus: "success", subjectCount: 0 })).toBe("loading")
    expect(subjectsGate({ overviewStatus: "success", profileStatus: "pending", subjectCount: 0 })).toBe("loading")
    // A source that may still bring subjects outranks one that already failed.
    expect(subjectsGate({ overviewStatus: "error", profileStatus: "pending", subjectCount: 0 })).toBe("loading")
  })

  it("is an error when nothing is known and a source failed", () => {
    expect(subjectsGate({ overviewStatus: "error", profileStatus: "success", subjectCount: 0 })).toBe("error")
    expect(subjectsGate({ overviewStatus: "success", profileStatus: "error", subjectCount: 0 })).toBe("error")
  })

  it("only says there are no subjects once both loaded and found none", () => {
    expect(subjectsGate({ overviewStatus: "success", profileStatus: "success", subjectCount: 0 })).toBe("none")
  })
})

describe("resolvePapersSubject", () => {
  it("starts on the first subject", () => {
    expect(resolvePapersSubject(SUBJECTS, null)).toEqual({ code: "0580", name: "Maths" })
  })

  it("follows the student's pick", () => {
    expect(resolvePapersSubject(SUBJECTS, "0625")).toEqual({ code: "0625", name: "Physics" })
  })

  it("falls back to the first subject when the pick has left the list", () => {
    expect(resolvePapersSubject(SUBJECTS, "4037")).toEqual({ code: "0580", name: "Maths" })
  })

  it("has no subject, not a blank name, when the list is empty", () => {
    expect(resolvePapersSubject([], null)).toEqual({ code: "", name: "" })
    expect(resolvePapersSubject([], "0580")).toEqual({ code: "", name: "" })
  })
})

describe("gatePapersQuery: cached papers outlive a failed refresh", () => {
  const data: PastPapers = { subjectCode: "0580", papers: [paper()] }
  const base = { error: null, refetch: () => {} }

  it("keeps the list when a refresh fails, and says so", () => {
    const gated = gatePapersQuery({ ...base, status: "error", data, error: new Error("boom") })
    expect(gated.query.status).toBe("success")
    expect(gated.query.data).toBe(data)
    expect(gated.refreshFailed).toBe(true)
  })

  it("is a real error when nothing was cached", () => {
    const gated = gatePapersQuery({ ...base, status: "error", data: undefined, error: new Error("boom") })
    expect(gated.query.status).toBe("error")
    expect(gated.refreshFailed).toBe(false)
  })

  it("passes pending and success through untouched", () => {
    expect(gatePapersQuery({ ...base, status: "pending", data: undefined, fetchStatus: "idle" })).toMatchObject({
      query: { status: "pending", fetchStatus: "idle" },
      refreshFailed: false,
    })
    expect(gatePapersQuery({ ...base, status: "success", data })).toMatchObject({ query: { status: "success" }, refreshFailed: false })
  })

  it("hands the retry through", () => {
    const refetch = vi.fn()
    gatePapersQuery({ status: "error", data, error: null, refetch }).query.refetch()
    expect(refetch).toHaveBeenCalledTimes(1)
  })
})

describe("effectiveOption", () => {
  it("keeps a choice the sheet offers", () => {
    expect(effectiveOption(paperSheetView(paper(), "Maths"), "print")).toBe("print")
    expect(effectiveOption(paperSheetView(paper(), "Maths"), "timed")).toBe("timed")
  })

  it("never lets a missing timed option stay chosen", () => {
    expect(effectiveOption(paperSheetView(paper({ durationMinutes: null }), "Maths"), "timed")).toBe("print")
  })
})

describe("printFailure", () => {
  it("treats a 409 as final: the paper has nothing to print, so retrying cannot help", () => {
    const failure = printFailure(new ApiError(409, "nothing servable"))
    expect(failure.retryable).toBe(false)
    expect(failure.message).toBe("We can’t print this one yet.")
  })

  it("treats everything else as worth another try", () => {
    for (const error of [new ApiError(500, "x"), new ApiError(0, "offline"), new Error("x"), "x"]) {
      expect(printFailure(error)).toEqual({ message: "Couldn’t get this paper ready. Try again.", retryable: true })
    }
  })
})

describe("printPath and canDismissSheet", () => {
  it("opens the print view of the new assignment", () => {
    expect(printPath("a-1")).toBe("/student/practice/print/a-1")
  })

  it("holds the sheet open while the paper is being made, so the navigation cannot land from a dead sheet", () => {
    expect(canDismissSheet(true)).toBe(false)
    expect(canDismissSheet(false)).toBe(true)
  })
})

describe("runPrint", () => {
  const created = { assignmentId: "a-9", quizId: "q", questionCount: 18, requestedCount: 18, topics: [], reason: null }
  function io(over: Partial<PrintIo> = {}): PrintIo & { mutate: ReturnType<typeof vi.fn>; navigate: ReturnType<typeof vi.fn> } {
    return { mutate: vi.fn(async () => created), navigate: vi.fn(), ...over } as never
  }

  it("asks for a timed paper only when timed is chosen", async () => {
    const view = paperSheetView(paper(), "Maths")
    const a = io()
    await runPrint(a, paper(), view, "timed")
    expect(a.mutate).toHaveBeenCalledWith({ paperId: "p1", timed: true })
    const b = io()
    await runPrint(b, paper(), view, "print")
    expect(b.mutate).toHaveBeenCalledWith({ paperId: "p1", timed: false })
  })

  it("an option the paper does not offer is sent as untimed", async () => {
    const noClock = paper({ durationMinutes: null })
    const a = io()
    await runPrint(a, noClock, paperSheetView(noClock, "Maths"), "timed")
    expect(a.mutate).toHaveBeenCalledWith({ paperId: "p1", timed: false })
  })

  it("lands on the print view once it is made", async () => {
    const a = io()
    const outcome = await runPrint(a, paper(), paperSheetView(paper(), "Maths"), "print")
    expect(a.navigate).toHaveBeenCalledWith("/student/practice/print/a-9")
    expect(outcome).toEqual({ kind: "created", to: "/student/practice/print/a-9" })
  })

  it("stays put and reports the failure when making it fails", async () => {
    const a = io({ mutate: vi.fn(async () => Promise.reject(new ApiError(500, "x"))) as never })
    const outcome = await runPrint(a, paper(), paperSheetView(paper(), "Maths"), "print")
    expect(a.navigate).not.toHaveBeenCalled()
    expect(outcome).toEqual({ kind: "failed", failure: { message: "Couldn’t get this paper ready. Try again.", retryable: true } })
  })

  it("never asks the server for a paper with nothing to print", async () => {
    const empty = paper({ questionCount: 0 })
    const a = io()
    const outcome = await runPrint(a, empty, paperSheetView(empty, "Maths"), "print")
    expect(a.mutate).not.toHaveBeenCalled()
    expect(a.navigate).not.toHaveBeenCalled()
    expect(outcome).toEqual({ kind: "blocked" })
  })
})

describe("noSubjectsCopy", () => {
  it("is short, plain and has no exclamation mark", () => {
    const copy = noSubjectsCopy()
    expect(copy.heading).toBe("No subjects yet")
    expect(copy.body.length).toBeGreaterThan(0)
    expect(`${copy.heading} ${copy.body}`).not.toContain("!")
  })
})
