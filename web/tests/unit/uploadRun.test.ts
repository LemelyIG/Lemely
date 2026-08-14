import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { canStartRun, runPhase } from "@/lib/uploadRun"
import type { UploadRun } from "@/lib/studentTypes"

/*
 * Recovering a marking run that outlived its browser tab (P6.2, audit M4).
 *
 * The defect underneath M4 was not in the screen. `POST /student/correct` marks
 * on a background thread that does not stop when the client disconnects, so a
 * reload never lost the marking — only the thing reporting on it. What was
 * missing was any record that a run was *in flight*: `UploadStatus.processing`
 * shipped in the first migration and no code path had ever written it, so a
 * paper being marked right now was indistinguishable in the database from a
 * scan somebody uploaded and abandoned.
 *
 * Two classes of claim are pinned here, and they are pinned differently.
 *
 * The phase decision is real logic and is tested as logic. The two rules that
 * are *not* expressible as a pure function — never re-run a paper that is
 * already being marked, and never redraw progress the screen cannot know — are
 * read off the source, which is weaker and is stated as such. The Python side
 * (`tests/test_student_correct.py`) is where the same rules are proven against
 * a real database and a real run.
 */

const SRC = join(__dirname, "..", "..", "src")
const HOOKS = readFileSync(join(SRC, "lib", "hooks", "useStudentApi.ts"), "utf8")
const SCREEN = readFileSync(
  join(SRC, "portals", "student", "screens", "CorrectPaper.tsx"),
  "utf8",
)

function run(over: Partial<UploadRun> = {}): UploadRun {
  return {
    paperId: "11111111-1111-4111-8111-111111111111",
    status: "processing",
    filename: "physics.pdf",
    startedAt: "2026-08-14T10:00:00Z",
    stale: false,
    ...over,
  }
}

describe("runPhase", () => {
  it("has nothing to recover when there is no run", () => {
    expect(runPhase(null)).toBe("none")
    expect(runPhase(undefined)).toBe("none")
  })

  it("treats a live run as something to wait for", () => {
    expect(runPhase(run({ status: "processing", stale: false }))).toBe("waiting")
  })

  /*
   * The one that matters most. A `processing` row can only stay `processing`
   * because the process holding it died, and nothing will ever come back to
   * finish it — so a screen that keeps saying "still marking" is making a
   * promise with nothing behind it, forever, on the flow the product exists
   * for.
   */
  it("stops promising a result once the run is stale", () => {
    expect(runPhase(run({ status: "processing", stale: true }))).toBe("stopped")
  })

  it("treats a reported failure as stopped, and never as stale", () => {
    // `failed` is a run that said why. `stale` is one that vanished. They share
    // a phase because the way out is the same button, not because they are the
    // same event — which is why the caller keeps the run and picks its own copy.
    expect(runPhase(run({ status: "failed", stale: false }))).toBe("stopped")
  })

  it("sends a finished run to its result", () => {
    expect(runPhase(run({ status: "complete", stale: false }))).toBe("done")
  })

  /*
   * `pending` is a scan that was stored and never marked, which is what a
   * student produces every time they choose a file and change their mind.
   * Reading it as "in flight" is exactly the defect that made the platform
   * console's queue depth grow forever, and here it would be worse: a waiting
   * state nothing can ever move the screen out of.
   */
  it("does not wait on an upload that was never marked", () => {
    expect(runPhase(run({ status: "pending" }))).toBe("none")
  })
})

describe("canStartRun", () => {
  it("refuses to start a second run over a paper already being marked", () => {
    expect(
      canStartRun({ phase: "waiting", hasScan: true, hasUploadedPaper: true }),
    ).toBe(false)
  })

  /*
   * After a reload the `File` is gone and the scan is not. Requiring the local
   * file is what made a run that stopped a dead end: the only way forward was
   * to find the paper and photograph it again, to re-upload a scan the server
   * was already holding.
   */
  it("can restart from a scan the server holds, with no local file", () => {
    expect(
      canStartRun({ phase: "stopped", hasScan: false, hasUploadedPaper: true }),
    ).toBe(true)
  })

  it("can start from a local file with nothing uploaded yet", () => {
    expect(
      canStartRun({ phase: "none", hasScan: true, hasUploadedPaper: false }),
    ).toBe(true)
  })

  it("has nothing to mark with neither", () => {
    expect(
      canStartRun({ phase: "none", hasScan: false, hasUploadedPaper: false }),
    ).toBe(false)
  })
})

describe("how a recovered run is followed", () => {
  /*
   * Discovery and polling are separate endpoints because they end differently.
   * `/uploads/active` stops naming a paper the instant it reaches a terminal
   * status, so a client polling only that would watch its run disappear and
   * never learn whether it was marked or failed.
   */
  it("polls the paper, and stops on a terminal status", () => {
    expect(HOOKS).toMatch(/TERMINAL[^\n]*new Set\(\["complete", "failed"\]\)/)
    expect(HOOKS).toMatch(/TERMINAL\.has\(query\.state\.data\.status\) \? false :/)
  })

  it("does not poll the discovery endpoint", () => {
    const discovery = HOOKS.slice(
      HOOKS.indexOf("export function useActiveUpload"),
      HOOKS.indexOf("export function useUploadRun"),
    )
    expect(discovery).not.toMatch(/refetchInterval/)
  })

  /*
   * Not a style preference. Every poll is a request from a phone that may be on
   * the bad connection this whole path exists to survive, and a full mark takes
   * minutes — so a sub-second interval would spend the case it is for to save a
   * few seconds on the case it is not.
   */
  it("polls at a human interval, not a streaming one", () => {
    const match = HOOKS.match(/const RUN_POLL_MS = (\d+)/)
    expect(match, "RUN_POLL_MS is the poll cadence; keep it named").not.toBeNull()
    expect(Number(match?.[1])).toBeGreaterThanOrEqual(2000)
  })
})

describe("what the recovered screen must not do", () => {
  /*
   * Source-read, and weaker than the tests above: it proves the screen still
   * says the right thing, not that it does it. The behavioural proof is
   * `test_active_upload_finds_a_run_in_flight` in the Python suite, which runs
   * a real pipeline against a real database.
   */
  it("never re-runs a paper it recovered", () => {
    // `runCorrection` is the only call that starts marking, and the recovery
    // path must not reach it. It appears exactly where the tab drives its own
    // stream, and nowhere in the recovery effect.
    const start = SCREEN.indexOf("useEffect(() => {")
    const end = SCREEN.indexOf("}, [phase, strandedRun, navigate])", start)
    expect(start, "the recovery effect moved; move this pin with it").toBeGreaterThan(-1)
    expect(end, "the recovery effect's dependency list changed").toBeGreaterThan(start)
    expect(SCREEN.slice(start, end)).not.toMatch(/runCorrection|uploadScan/)
  })

  /*
   * The reveal is for a figure that arrived while this reader was watching it.
   * A paper marked in another tab, or before a reload, is not that, so the
   * recovery navigation carries no `state` and `PaperResult` renders it plainly.
   */
  it("sends a recovered result to the result screen without the reveal", () => {
    expect(SCREEN).toMatch(/navigate\(`\/student\/result\/\$\{strandedRun\.paperId\}`\)/)
  })

  /*
   * The stage list is a claim about which step the pipeline reached, and a
   * recovered reader has no such information: the SSE frames go to a bus with
   * no replay and the tab that was reading them is gone. Ticking stages off
   * from a status word is the invented progress S-14 rules out by name.
   */
  it("does not draw the stage panel for a run it did not stream", () => {
    const recovered = SCREEN.slice(
      SCREEN.indexOf("{strandedRun ? ("),
      SCREEN.indexOf("<ProcessingState"),
    )
    expect(recovered.length).toBeGreaterThan(0)
    expect(recovered).not.toMatch(/ProcessingState/)
  })
})
