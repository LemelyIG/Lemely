import type { UploadRun } from "@/lib/studentTypes"

/*
 * What a marking run that outlived its browser tab means for the screen (P6.2).
 *
 * `POST /student/correct` marks on a background thread that does not stop when
 * the client disconnects, so a reload, a backgrounded tab on a phone, or a lost
 * signal takes away the thing *reporting* on a run, never the run. The screen
 * recovers it by reading `/student/uploads/active` — and then has to turn four
 * statuses plus a staleness flag into the two questions it actually asks: may I
 * start marking, and what do I tell the reader.
 *
 * That decision lives here rather than in the screen for the reason every
 * `*Outcome.ts` module in this codebase exists: the web test runner is
 * `environment: "node"` with no jsdom, so logic inside a component can only be
 * pinned by reading its source, and a source-reading gate cannot tell a rule
 * that works from a rule that merely still has the right words in it.
 */

/**
 * What the screen should do about a recovered run.
 *
 * - `none` — there is nothing to recover, the ordinary case.
 * - `waiting` — still being marked. Say so, and do not start a second run.
 * - `stopped` — it will not finish. Offer to start again.
 * - `done` — it finished; the result exists and the screen should go to it.
 */
export type RunPhase = "none" | "waiting" | "stopped" | "done"

/**
 * Classify a recovered run.
 *
 * `stale` is the server's judgement that a `processing` row is one nobody will
 * ever finish — a process that died holding it — and it is deliberately treated
 * as `stopped` rather than as a third thing on screen. From the student's side
 * the two are the same event: the marking is not coming, and the way out is the
 * same button.
 *
 * A `failed` run is never stale, and the distinction matters here: `failed` is a
 * run that reported a reason, `stale` is one that vanished. They land in the
 * same phase but they do not share copy, which is why this returns the phase and
 * the caller keeps the run.
 */
export function runPhase(run: UploadRun | null | undefined): RunPhase {
  if (!run) return "none"
  if (run.status === "complete") return "done"
  if (run.status === "failed") return "stopped"
  if (run.status === "processing") return run.stale ? "stopped" : "waiting"
  /*
   * `pending` reaches here only if a caller passes a run it did not get from
   * `/uploads/active` (which never returns one). A stored-but-never-marked scan
   * is not a run in flight and must not put the screen into a waiting state it
   * can never leave: nothing is going to move that row.
   */
  return "none"
}

/**
 * Whether a *new* marking run may be started right now.
 *
 * The hard constraint is not a UI nicety. Two runs over one scan would spend a
 * hard-capped Gemini budget twice, write a second attempt row for the same
 * paper, and cross-talk on an event bus that is process-global and
 * single-stream, so both readers would see a mix of the two.
 *
 * `hasScan` is a local file; `hasUploadedPaper` is a scan the server already
 * holds. Either is enough, which is the part that makes a reloaded failure
 * recoverable at all: after a reload the `File` is gone and the scan is not.
 *
 * `emailVerified` is D7.5's soft gate, brought forward. `POST /student/correct`
 * is guarded by `require_verified_email` and answers
 * `403 {"code": "email_unverified"}`, so starting a run for an unverified
 * account spends a click, an upload's worth of waiting and a stage animation
 * to reach a refusal the app already knew was coming. It belongs here rather
 * than in the screen's JSX because the screen calls this once and feeds both
 * of its start buttons from the result, so one input covers both.
 *
 * Note the caller's contract: pass `true` when the answer is not yet known.
 * A pending profile must not disable the button, for the same reason
 * `verifyEmailBannerState` keeps the banner hidden while the profile is
 * pending. The app does not know, and acting on what it does not know is how
 * a verified student ends up looking at a dead button during a page load.
 */
export function canStartRun({
  phase,
  hasScan,
  hasUploadedPaper,
  emailVerified,
}: {
  phase: RunPhase
  hasScan: boolean
  hasUploadedPaper: boolean
  emailVerified: boolean
}): boolean {
  if (!emailVerified) return false
  if (phase === "waiting") return false
  return hasScan || hasUploadedPaper
}
