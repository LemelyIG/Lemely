import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * No screen renders a machine's words to a person (P6.2).
 *
 * This defect has now been found and fixed on five separate occasions — the
 * marking stream (P4.2), the friends screens (P4.4), the teacher portal's 44
 * sites (P4.5), the parent portal's four (P4.6), the auth screens (P4.7) — and
 * each time the fix was the same shape and the report said the family was
 * closed. It was not. Phase 6.2 found **fifteen more live sites**, including
 * the student's two most-read screens, and the reason is worth writing down:
 *
 *   the failure-copy modules were written surface by surface, and a screen
 *   redesigned BEFORE its module existed was never revisited. `Overview` and
 *   `PaperResult` are surfaces 1 and 2; `studentOutcome.ts` arrived on surface
 *   10. Nothing connected the two facts, because nothing was looking.
 *
 * So this is a gate rather than a sixth sweep. It walks the tree instead of
 * reading a file list, deliberately: P4.10's finding was that a hand-maintained
 * gate list is a list some screen is missing from, and that is exactly the
 * mechanism that let this survive five fixes.
 *
 * WHAT IT CATCHES. `err.message` on an `Error` from this client is one of:
 * FastAPI's `detail` (a Python repr, a bare UUID, or a stringified exception
 * for most of these routers), the status line ("500 Internal Server Error"), or
 * the browser's own "Failed to fetch" for a dropped connection — which is the
 * one a phone on a bad train produces, i.e. the single most likely failure this
 * product has.
 *
 * WHAT IT DOES NOT CATCH. Reading `.message` to *classify* an error, or to log
 * it, is fine and common. The rule is about the value reaching a render, so the
 * check is scoped to JSX attribute and expression positions and to the state
 * setters that feed them.
 */

const SRC = join(__dirname, "..", "..", "src")

/** Every `.ts`/`.tsx` under `src/`, found rather than listed. */
function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path))
      continue
    }
    if (entry.endsWith(".ts") || entry.endsWith(".tsx")) out.push(path)
  }
  return out
}

/**
 * Lines that put an error's own `.message` somewhere a reader will see it.
 *
 * Three shapes, which are the three this codebase has actually produced:
 *
 *   body={error.message}                     a prop taking a sentence
 *   {complete.error.message}                 interpolated into copy
 *   setSubmitError(err.message)              stashed for a later render
 *
 * Comments are stripped first. Every fix in this family carries a note
 * explaining what the old code did, and those notes quote the code they
 * replaced — so a gate that read them would fire on its own documentation and
 * teach people to stop writing it down.
 */
function renderedMessages(source: string): string[] {
  /*
   * The receiver has to be error-shaped, not merely something with a
   * `.message`. The first draft of this gate matched any `.message` reaching a
   * setter and reported `setQuietError(result.message)` in the notification
   * settings — where `result` is this codebase's own quiet-hours validator and
   * its `message` is a sentence written for this exact reader. That is the
   * opposite of the defect, and a gate that reports it teaches people to route
   * good copy through an outcome module to make a test go quiet.
   */
  const errorMessage = /\b(?:err|error|[A-Za-z_$][\w$]*(?:Error|error))\s*\??\.\s*message\b/

  const withoutBlockComments = source.replace(/\/\*[\s\S]*?\*\//g, "")
  return withoutBlockComments
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .filter((line) => {
      if (!errorMessage.test(line)) return false
      // ...and it has to be in a render position. Reading an error's message to
      // classify or log it is fine, and common.
      return (
        /\b(?:body|message|title|heading|detail|label|children)\s*=\s*\{/.test(line) ||
        /\{[^{}]*\.message[^{}]*\}/.test(line) ||
        /\bset[A-Z]\w*(?:Error|Message)\s*\(/.test(line) ||
        /\bfailActiveStage\s*\(/.test(line)
      )
    })
    .map((line) => line.trim())
}

/*
 * PR 1B (client error reporting) exemption.
 *
 * `renderedMessages`'s "`.message` inside a `{...}` on one line" check exists
 * to catch a JSX expression container (`<p>{err.message}</p>`) — and cannot,
 * by construction, tell that shape apart from a plain object literal that
 * happens to also fit on one line, e.g.
 * `return { message: error.message, stack: error.stack ?? null }`. That is
 * exactly the line `lib/clientErrors.ts` builds `POST /api/client-errors`'s
 * request body with: a telemetry payload sent to the backend's structured
 * logging, never a JSX prop or a `useState` setter, so it can never reach a
 * render — see that file's own module comment for the fuller argument
 * (`request()`/`ApiError` are the paths this repo's other error-copy modules
 * exist to launder; this one is not in that family at all).
 *
 * The allowlist below is a line-shape match, not a whole-file exemption.
 * `lib/clientErrors.ts` is an ordinary `.ts` module like `studentOutcome.ts`
 * or `queryFailure.ts` — nothing about the `.ts` extension says a file holds
 * no rendered sentences, and exempting the whole file on that premise would
 * have hidden a real offender landing in this file later. What actually
 * cannot fire the gate is the specific payload-object shape
 * (`message: error.message` / `stack: error.stack` as object-literal
 * fields), so that is what is matched: a line containing both `message:`
 * and `.message` (or `stack:` and `.stack`) as an object-literal field,
 * never a bare `{error.message}` JSX expression container, which this
 * allowlist does not touch and the gate still catches.
 *
 * As written today, `describeThrown()` in `clientErrors.ts` reads
 * `error.message`/`error.stack` through a helper rather than inlining them
 * into the report object literal (see that function's own doc comment: the
 * indirection is there to survive a getter that itself throws, not for this
 * gate), so this entry currently matches no line in the file at all — see
 * "clientErrors.ts's current message/stack lines pass the gate on their own"
 * below. Kept anyway, narrowly, as the documented answer for the shape this
 * file would go back to producing if that ever changes, rather than making
 * a future author rediscover this exact reasoning from scratch.
 */
const TELEMETRY_PAYLOAD_LINE_SHAPES: [file: string, pattern: RegExp, reason: string][] = [
  [
    "lib/clientErrors.ts",
    /\b(?:message|stack)\s*:\s*[A-Za-z_$][\w$]*\.(?:message|stack)\b/,
    "buildClientErrorReport() copies Error#message/#stack into object-" +
      "literal fields of the client-error report body POSTed to the " +
      "backend's structured logging. Read for telemetry, never assigned " +
      "to a render.",
  ],
]

describe("§6.2 no machine text reaches a reader", () => {
  it("renders no error's own message anywhere under src/", () => {
    const offenders: string[] = []
    for (const file of sourceFiles(SRC)) {
      const relative = file.slice(SRC.length + 1)
      const exemptPattern = TELEMETRY_PAYLOAD_LINE_SHAPES.find(([f]) => f === relative)?.[1]
      for (const line of renderedMessages(readFileSync(file, "utf8"))) {
        if (exemptPattern?.test(line)) continue
        offenders.push(`${relative}: ${line}`)
      }
    }
    expect(
      offenders,
      "Route this through the portal's outcome module instead " +
        "(studentOutcome / teacherOutcome / parentOutcome / authOutcome / " +
        "settingsOutcome / friendOutcome / correctionOutcome). If the backend " +
        "genuinely wrote that sentence for this reader, say so at the call " +
        "site the way correctionOutcome.ts does, and widen this gate with the " +
        "reason attached. If it never reaches a render at all (a telemetry " +
        "payload, say), add its line shape to TELEMETRY_PAYLOAD_LINE_SHAPES " +
        "above instead, with the same kind of reason.",
    ).toEqual([])
  })

  it("keeps the telemetry allowlist honest: each entry's file still exists and is real .ts", () => {
    const stale = TELEMETRY_PAYLOAD_LINE_SHAPES.filter(([relative]) => {
      const absolute = join(SRC, relative)
      return !statSync(absolute, { throwIfNoEntry: false })?.isFile() || relative.endsWith(".tsx")
    })
    expect(stale, "listed but gone, or a .tsx that could legitimately render JSX").toEqual([])
  })

  it("the clientErrors.ts allowlist entry matches the payload shape it names, on a line built that way", () => {
    // Pins the pattern itself, independent of whatever describeThrown()
    // happens to look like today: if a future edit to clientErrors.ts goes
    // back to building the report as one inline object literal
    // (`{ message: error.message, stack: error.stack ?? null }`), the
    // pattern below is what would keep that line from being a false
    // positive, so this checks it still recognises that exact shape.
    const [, pattern] = TELEMETRY_PAYLOAD_LINE_SHAPES.find(
      ([relative]) => relative === "lib/clientErrors.ts",
    )!
    expect(pattern.test("return { message: error.message, stack: error.stack ?? null }")).toBe(
      true,
    )
    // And it stays narrow: an ordinary rendered-message line is untouched by
    // it, so the allowlist cannot be used to hide a real offender under a
    // filename it happens to share.
    expect(pattern.test("body={error.message}")).toBe(false)
  })

  it("clientErrors.ts's current message/stack lines pass the gate on their own, with no allowlist entry needed", () => {
    // describeThrown() (PR 1 fix for the "reportClientError can throw" review
    // finding) reads error.message/error.stack through a helper rather than
    // inlining them into the report object literal, so as written today this
    // file produces no line the gate would flag in the first place — the
    // allowlist entry above is a defensive line-shape match for a payload
    // shape this file no longer happens to contain, not a carve-out this
    // file is currently relying on. Asserted directly here rather than left
    // as an inference from the file-level test above, which would pass the
    // same way whether this file needed the allowlist or not.
    const source = readFileSync(join(SRC, "lib/clientErrors.ts"), "utf8")
    expect(renderedMessages(source)).toEqual([])
  })

  /*
   * The gate has to be able to see the shapes it claims to cover, or it is the
   * vacuous check D6.1 spent a phase on. Each of these is a real line this
   * phase removed from the product.
   */
  it("recognises each shape it claims to catch", () => {
    expect(renderedMessages(`body={error.message}`)).toHaveLength(1)
    expect(renderedMessages(`body={dueQuery.error?.message}`)).toHaveLength(1)
    expect(
      renderedMessages(`Couldn't rebuild your plan: {rebuild.error.message}`),
    ).toHaveLength(1)
    expect(
      renderedMessages(`setSubmitError(err instanceof Error ? err.message : "x")`),
    ).toHaveLength(1)
    expect(
      renderedMessages(`failActiveStage(prev, err instanceof Error ? err.message : String(err))`),
    ).toHaveLength(1)
  })

  it("leaves classification and logging alone", () => {
    // Reading `.message` to decide something is not rendering it.
    expect(renderedMessages(`if (err.message.includes("quota")) return QUOTA`)).toEqual([])
    expect(renderedMessages(`console.warn(err.message)`)).toEqual([])
    /*
     * And a `message` that is not an error's. `quietHoursUpdate` returns a
     * sentence this codebase wrote for this reader; routing it through an
     * outcome module to quiet a test would replace good copy with generic copy.
     */
    expect(renderedMessages(`setQuietError(result.message)`)).toEqual([])
    // And a note explaining a fix must not fire the gate that prompted it.
    expect(renderedMessages(`/* this used to render body={error.message} */`)).toEqual([])
    expect(renderedMessages(`// it printed err.message verbatim`)).toEqual([])
  })
})
