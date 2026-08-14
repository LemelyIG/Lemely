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

describe("§6.2 no machine text reaches a reader", () => {
  it("renders no error's own message anywhere under src/", () => {
    const offenders: string[] = []
    for (const file of sourceFiles(SRC)) {
      for (const line of renderedMessages(readFileSync(file, "utf8"))) {
        offenders.push(`${file.slice(SRC.length + 1)}: ${line}`)
      }
    }
    expect(
      offenders,
      "Route this through the portal's outcome module instead " +
        "(studentOutcome / teacherOutcome / parentOutcome / authOutcome / " +
        "settingsOutcome / friendOutcome / correctionOutcome). If the backend " +
        "genuinely wrote that sentence for this reader, say so at the call " +
        "site the way correctionOutcome.ts does, and widen this gate with the " +
        "reason attached.",
    ).toEqual([])
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
