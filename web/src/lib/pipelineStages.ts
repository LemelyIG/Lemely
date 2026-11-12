import type {
  ProcessingStage,
  ProcessingStageProgress,
} from "@/components/ui/processing-state"

/*
 * Shared SSE-frame → C-10 `ProcessingState` reducer.
 *
 * The student's S-14 "correct a paper" panel
 * (`portals/student/screens/CorrectPaper.tsx`, streaming `/student/correct`)
 * is the only streaming consumer: advance one stage, back-fill the earlier
 * ones, annotate the running stage with non-stage-specific chatter, fail the
 * running stage on error.
 *
 * The teacher grading console once streamed the extract/grade endpoints and
 * drove the same machine; those SSE routes were removed (DS14) and it now
 * polls, keeping only `failActiveStage` for its error path. The helpers are
 * still shared rather than folded back into `CorrectPaper.tsx` because that
 * one helper is genuinely used by both, and because a second copy would be free
 * to drift from the first, and a progress panel that reports the pipeline
 * differently depending on which portal you are in is exactly the kind of
 * "roughly true" UI that S-14 forbids.
 *
 * Nothing here invents a value. `frameProgress` refuses to produce a counter
 * unless the frame actually carried one (S-14: "Resist a fake progress bar").
 */

/** The subset of an SSE frame these helpers read. Deliberately structural and
 * open-ended (`[key: string]: unknown`) so a frame type satisfies it without
 * importing anything from here. `StudentCorrectFrame` is the only implementor
 * left: the teacher console's `TeacherPipelineFrame` was removed with the
 * teacher SSE routes (DS14), and the structural shape is kept rather than
 * narrowed to that one type because it costs nothing and is what lets a
 * future frame schema opt in the same way. */
export interface PipelineFrameLike {
  type: string
  message?: string
  question_id?: string
  index?: number
  total?: number
  phase?: string
  [key: string]: unknown
}

/** Move a stage to active (or done, on completion), and mark every earlier
 * pending stage done too — forward progress on stage N implies stage N-1
 * finished, since the pipeline runs in this fixed order.
 *
 * `order` is the caller's stage-id sequence (the student panel's
 * `["extract", "scheme", "mark"]`, the teacher console's own list); it must
 * be in the same order as `stages`, since "earlier" is positional.
 *
 * `detail` and `progress` both use undefined to mean "leave what's there" —
 * a frame that says nothing new about the counter is not evidence that the
 * last real counter became wrong, and blanking it would blink the number off
 * and on between frames. */
export function advanceStage<S extends string>(
  stages: ProcessingStage[],
  order: readonly S[],
  id: S,
  detail: string | undefined,
  complete: boolean,
  progress?: ProcessingStageProgress,
): ProcessingStage[] {
  const idx = order.indexOf(id)
  return stages.map((s, i) => {
    if (i < idx) return s.status === "pending" ? { ...s, status: "done" } : s
    if (i === idx)
      return {
        ...s,
        status: complete ? "done" : "active",
        detail: detail ?? s.detail,
        progress: progress ?? s.progress,
      }
    return s
  })
}

/** Frame chatter that isn't stage-specific (gemini calls, budget notices)
 * updates whichever stage is currently active, rather than being dropped. */
export function annotateActiveStage(
  stages: ProcessingStage[],
  detail: string,
): ProcessingStage[] {
  const activeIdx = stages.findIndex((s) => s.status === "active")
  if (activeIdx === -1) return stages
  return stages.map((s, i) => (i === activeIdx ? { ...s, detail } : s))
}

/** Fail whichever stage is running (or the first stage, if nothing had
 * started yet — e.g. the initial upload itself failed). */
export function failActiveStage(
  stages: ProcessingStage[],
  errorMessage: string,
): ProcessingStage[] {
  const idx = stages.findIndex((s) => s.status === "active" || s.status === "pending")
  if (idx === -1) return stages
  return stages.map((s, i) => (i === idx ? { ...s, status: "error", errorMessage } : s))
}

/** The real per-question counter a frame carries, or undefined when it
 * carries none.
 *
 * `index`/`total` come straight off the wire (`correction_ai.py` and
 * `answer_extraction.py` publish them as the 1-based position in the work
 * list and that list's length). Frames from publishers that don't send them —
 * the terminal `phase: "complete"` summary, the teacher console's
 * cached-report replay branch — yield undefined, and C-10 then renders the
 * stage with no counter at all. That is the honest outcome: there is no
 * denominator to guess at, and a fabricated "of 20" would be exactly the
 * lying progress indicator S-14 rules out. A zero or negative `total` is
 * treated the same way, since "Question 3 of 0" is not a fact about
 * anything. */
export function frameProgress(
  frame: PipelineFrameLike,
): ProcessingStageProgress | undefined {
  const { index, total } = frame
  if (typeof index !== "number" || typeof total !== "number") return undefined
  if (!Number.isFinite(index) || !Number.isFinite(total) || total <= 0) return undefined
  return { current: index, total, unit: "question" }
}
