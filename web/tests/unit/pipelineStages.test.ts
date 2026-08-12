import { describe, expect, it } from "vitest"
import {
  advanceStage,
  annotateActiveStage,
  failActiveStage,
  frameProgress,
} from "@/lib/pipelineStages"
import type { PipelineFrameLike } from "@/lib/pipelineStages"
import type { ProcessingStage } from "@/components/ui/processing-state"

/*
 * The shared SSE-frame → C-10 stage reducer (`src/lib/pipelineStages.ts`).
 *
 * Both marking screens render their pipeline entirely out of what these four
 * functions return, so every claim C-10 makes on screen — this stage finished,
 * that one is running, this one failed with *that* message, "Question 7 of 21"
 * — is a claim one of these functions decided to make. That is what is pinned
 * here, and the bias of every assertion is the same: the panel may say less
 * than the backend did, never more.
 *
 * Two behaviours carry the file. Back-filling must not overwrite a stage that
 * already errored, because that would take a failure the reader was shown and
 * silently relabel it done. And `frameProgress` must refuse to produce a
 * counter from a frame that did not carry one — S-14's design note is explicit
 * ("Resist a fake progress bar. Real staged progress with honest per-stage
 * detail builds more trust than a smooth lying animation"), and a fabricated
 * denominator is the smallest possible version of that lie.
 *
 * The rendering of these stages is not covered here: this runner is
 * `environment: "node"` with no jsdom by design (see `vitest.config.ts`), so
 * what C-10 draws from a given stage list belongs to the Playwright suite.
 */

const ORDER = ["extract", "scheme", "mark"] as const
type StageId = (typeof ORDER)[number]

const LABELS: Record<StageId, string> = {
  extract: "Reading your answers",
  scheme: "Fetching the mark scheme",
  mark: "Marking your questions",
}

/** The student panel's three stages (`CorrectPaper.tsx`'s `initialStages`),
 * all pending unless the test says otherwise. Using the real screen's list
 * rather than a synthetic one keeps the positional "earlier stage" reasoning
 * these helpers depend on anchored to a pipeline that actually exists. */
function pipeline(
  overrides: Partial<Record<StageId, Partial<ProcessingStage>>> = {},
): ProcessingStage[] {
  return ORDER.map((id) => ({
    id,
    label: LABELS[id],
    status: "pending" as const,
    ...overrides[id],
  }))
}

function statuses(stages: ProcessingStage[]) {
  return stages.map((s) => s.status)
}

/** Frames arrive as parsed JSON, so `PipelineFrameLike`'s `index?: number` is
 * a hope about the wire and not a guarantee about the value — which is exactly
 * why `frameProgress` re-checks it at runtime. Tests that feed it a wrong-typed
 * field have to go through this to say so. */
function frame(raw: Record<string, unknown>): PipelineFrameLike {
  return raw as PipelineFrameLike
}

describe("advanceStage", () => {
  it("runs the named stage and back-fills the pending stages before it", () => {
    // A `marking_progress` frame is the first thing the marking stage says;
    // nothing ever announces that extraction finished. Forward progress on
    // stage N is the evidence that N-1 completed, because the backend runs
    // these in exactly this order.
    const next = advanceStage(pipeline(), ORDER, "mark", "Question 1 of 21", false)
    expect(statuses(next)).toEqual(["done", "done", "active"])
    expect(next[2].detail).toBe("Question 1 of 21")
  })

  it("leaves an earlier errored stage errored instead of back-filling it done", () => {
    // The load-bearing case. The mark-scheme fetch can fail while the run
    // continues, and the next marking frame walks back over that stage —
    // flipping it to "done" would erase a failure the reader was already shown
    // and replace it with a success that never happened.
    const failed = pipeline({
      extract: { status: "done" },
      scheme: { status: "error", errorMessage: "No mark scheme for 0625/42/M/J/24." },
    })
    const next = advanceStage(failed, ORDER, "mark", "Question 1 of 21", false)
    expect(statuses(next)).toEqual(["done", "error", "active"])
    expect(next[1].errorMessage).toBe("No mark scheme for 0625/42/M/J/24.")
  })

  it("says nothing about the stages that have not been reached", () => {
    const before = pipeline()
    const next = advanceStage(before, ORDER, "extract", "Reading page 1 of 6", false)
    expect(statuses(next)).toEqual(["active", "pending", "pending"])
    // Untouched stages come back by reference, so a re-render is confined to
    // the stage that actually changed.
    expect(next[1]).toBe(before[1])
    expect(next[2]).toBe(before[2])
  })

  it("marks the target done when the caller says it completed", () => {
    const next = advanceStage(pipeline(), ORDER, "extract", "6 pages read", true)
    expect(next[0].status).toBe("done")
    // Not "active": a stage left active keeps C-10's spinner running, which
    // claims work still in flight after the work stopped.
    expect(statuses(next)).toEqual(["done", "pending", "pending"])
  })

  it("attaches the counter it was handed", () => {
    const next = advanceStage(pipeline(), ORDER, "mark", "Question 7 of 21", false, {
      current: 7,
      total: 21,
      unit: "question",
    })
    expect(next[2].progress).toEqual({ current: 7, total: 21, unit: "question" })
  })

  it("keeps the last real detail and counter when a frame carries neither", () => {
    // `undefined` means "leave what's there", not "clear it". A frame that says
    // nothing new about the counter is not evidence the previous counter went
    // wrong, and blanking it would blink the number off and on between frames.
    const midRun = pipeline({
      mark: {
        status: "active",
        detail: "Question 7 of 21",
        progress: { current: 7, total: 21, unit: "question" },
      },
    })
    const next = advanceStage(midRun, ORDER, "mark", undefined, false)
    expect(next[2].detail).toBe("Question 7 of 21")
    expect(next[2].progress).toEqual({ current: 7, total: 21, unit: "question" })
  })

  it("does not mutate the list it was given", () => {
    // The screens hold these in React state and pass `prev` straight in.
    const before = pipeline({ extract: { status: "error", errorMessage: "boom" } })
    const snapshot = structuredClone(before)
    advanceStage(before, ORDER, "mark", "Question 1 of 21", false)
    expect(before).toEqual(snapshot)
  })

  it("changes nothing for a stage id that is not in the order", () => {
    // `indexOf` misses, so no stage is before it and none is it. A silent no-op
    // is the right failure mode: an unrecognised stage id is not grounds to
    // declare the stages ahead of it finished.
    const next = advanceStage(pipeline(), ORDER, "unknown" as StageId, "…", false)
    expect(statuses(next)).toEqual(["pending", "pending", "pending"])
  })
})

describe("annotateActiveStage", () => {
  it("writes the detail onto the running stage only", () => {
    // Chatter that names no stage — a Gemini call, a budget notice — belongs to
    // whatever is running rather than being dropped on the floor.
    const midRun = pipeline({
      extract: { status: "done", detail: "6 pages read" },
      scheme: { status: "active", detail: "Looking up 0625/42/M/J/24" },
    })
    const next = annotateActiveStage(midRun, "Asking Gemini for the mark scheme")
    expect(next[1].detail).toBe("Asking Gemini for the mark scheme")
    expect(next[0].detail).toBe("6 pages read")
    expect(next[2].detail).toBeUndefined()
    expect(statuses(next)).toEqual(["done", "active", "pending"])
  })

  it("drops the chatter when nothing is running yet", () => {
    // Before the first stage frame arrives there is no stage the message is
    // true of. It returns the same array, so React sees no state change.
    const untouched = pipeline()
    expect(annotateActiveStage(untouched, "Connecting")).toBe(untouched)
  })

  it("drops the chatter after the run has ended", () => {
    const finished = pipeline({
      extract: { status: "done" },
      scheme: { status: "error", errorMessage: "No mark scheme found." },
      mark: { status: "done" },
    })
    expect(annotateActiveStage(finished, "Cleaning up")).toBe(finished)
    expect(finished[1].errorMessage).toBe("No mark scheme found.")
  })
})

describe("failActiveStage", () => {
  it("fails the running stage with the backend's own message", () => {
    const midRun = pipeline({
      extract: { status: "done" },
      scheme: { status: "active" },
    })
    const next = failActiveStage(midRun, "No mark scheme for 0625/42/M/J/24.")
    expect(statuses(next)).toEqual(["done", "error", "pending"])
    // C-10 renders no generic fallback, so a stage that errors without a
    // message shows the reader nothing about why.
    expect(next[1].errorMessage).toBe("No mark scheme for 0625/42/M/J/24.")
    // The stages that genuinely finished keep their result.
    expect(next[0].status).toBe("done")
  })

  it("fails the first pending stage when nothing had started", () => {
    // The upload itself failed, before any frame arrived. The failure has to
    // land somewhere visible rather than leaving three pending stages that
    // will never move.
    const next = failActiveStage(pipeline(), "Upload failed: file too large (25 MB limit).")
    expect(statuses(next)).toEqual(["error", "pending", "pending"])
    expect(next[0].errorMessage).toBe("Upload failed: file too large (25 MB limit).")
  })

  it("no-ops when every stage has already finished one way or another", () => {
    // A late error frame after the pipeline is settled has no stage left to
    // attach to, and inventing one would put a failure on work that succeeded.
    const settled = pipeline({
      extract: { status: "done" },
      scheme: { status: "done" },
      mark: { status: "error", errorMessage: "The marking service is unavailable." },
    })
    expect(failActiveStage(settled, "The stream ended unexpectedly.")).toBe(settled)
    expect(settled[2].errorMessage).toBe("The marking service is unavailable.")
  })

  it("no-ops on a fully completed pipeline", () => {
    const allDone = pipeline({
      extract: { status: "done" },
      scheme: { status: "done" },
      mark: { status: "done" },
    })
    expect(failActiveStage(allDone, "The stream ended unexpectedly.")).toBe(allDone)
  })
})

describe("frameProgress", () => {
  it("reports the counter the frame actually carried", () => {
    // `index`/`total` come off the wire as the 1-based position in the work
    // list and that list's length (`correction_ai.py`, `answer_extraction.py`).
    expect(frameProgress({ type: "marking_progress", index: 7, total: 21 })).toEqual({
      current: 7,
      total: 21,
      unit: "question",
    })
  })

  it("reads the counter and nothing else off the frame", () => {
    // Neighbouring fields are not evidence about the counter: a `question_id`
    // is not an index and a `phase` is not a denominator.
    expect(
      frameProgress({
        type: "marking_progress",
        index: 1,
        total: 3,
        question_id: "1(a)",
        phase: "marking",
        message: "Marking question 1(a)",
      }),
    ).toEqual({ current: 1, total: 3, unit: "question" })
  })

  it.each([
    // The terminal summary from `/student/correct` reports the phase, not a
    // position — there is no "of 21" left to state.
    ["the frame carries no index", frame({ type: "progress", phase: "complete", total: 21 })],
    ["the frame carries no total", frame({ type: "marking_progress", index: 3 })],
    // The teacher console's cached-report replay branch publishes neither.
    ["the frame carries neither", frame({ type: "stage", message: "Loading cached report" })],
    // "Question 3 of 0" is not a fact about anything.
    ["the total is 0", frame({ type: "marking_progress", index: 3, total: 0 })],
    ["the total is negative", frame({ type: "marking_progress", index: 3, total: -21 })],
    ["the index is a string", frame({ type: "marking_progress", index: "3", total: 21 })],
    ["the total is a string", frame({ type: "marking_progress", index: 3, total: "21" })],
    ["the index is null", frame({ type: "marking_progress", index: null, total: 21 })],
    ["the total is null", frame({ type: "marking_progress", index: 3, total: null })],
    ["the total is a bare object", frame({ type: "marking_progress", index: 3, total: {} })],
    ["the index is NaN", frame({ type: "marking_progress", index: Number.NaN, total: 21 })],
    ["the total is NaN", frame({ type: "marking_progress", index: 3, total: Number.NaN })],
    [
      "the total is Infinity",
      frame({ type: "marking_progress", index: 3, total: Number.POSITIVE_INFINITY }),
    ],
  ])("invents no counter when %s", (_label, f) => {
    // The whole point of the helper, and the one assertion in this file that
    // must never be softened: with no real counter on the wire, C-10 renders
    // the stage with no counter at all. There is no denominator to guess at,
    // and "Question 3 of 20" when the backend never said 20 is precisely the
    // lying progress indicator S-14 rules out.
    expect(frameProgress(f)).toBeUndefined()
  })

  it("never fabricates a total from a partial frame", () => {
    // Stated separately from the table because it is the specific temptation:
    // an index with no denominator must not become "3 of 3" or "3 of 100". The
    // absence of a total is total absence of a counter.
    expect(frameProgress({ type: "marking_progress", index: 3 })).toBeUndefined()
  })

  it("passes a zero index straight through", () => {
    // Both publishers enumerate from 1, so this should not arrive. It is
    // pinned because the filter is about *absence* (`typeof`), not falsiness:
    // a truthiness check here would drop a real value the wire had sent.
    expect(frameProgress({ type: "marking_progress", index: 0, total: 21 })).toEqual({
      current: 0,
      total: 21,
      unit: "question",
    })
  })

  it("reports an index past its own total rather than clamping it", () => {
    // If the backend ever disagrees with itself, C-10 shows what it said. A
    // clamp would hide a real backend bug behind a plausible-looking number.
    expect(frameProgress({ type: "marking_progress", index: 22, total: 21 })).toEqual({
      current: 22,
      total: 21,
      unit: "question",
    })
  })
})
