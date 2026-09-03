import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Finding 14 · source-text gates for `components/route-error.tsx`'s wiring.
 *
 * `RouteErrorScreen`/`PortalErrorFallback` are components wired to
 * `useRouteError`, real routing context and the real browser — none of that
 * is mountable under this suite's DOM-less Node environment
 * (`vitest.config.ts`, D3.20), the same reason `offlineBanner.test.ts` reads
 * its four portal layouts as text instead of rendering them. These gates do
 * the same thing for this file's own wiring rules, each pinning a fact the
 * SHOULD-FIX findings on this component depend on staying true:
 *  - the standalone export only ever renders `frame="standalone"`, the
 *    portal export only ever `frame="portal"` (never crossed);
 *  - `service-trouble` mounts `useServiceHealth`;
 *  - a chunk-load error is never reported (SHOULD-FIX 13);
 *  - the guarded reload (`handleChunkError`, a real side effect) is called
 *    from a `useEffect`, never from a render body (SHOULD-FIX 5).
 *
 * `sliceFunction` below finds a named function's full body by depth-counting
 * parens (to skip past its parameter list, however many nested braces or
 * parens that list itself contains — `PortalErrorFallback`'s own signature
 * has both) and then depth-counting braces from the real body's opening `{`.
 * Comments are stripped first (`stripComments`, shared with the six other
 * gates that already read `.tsx` as text) so prose mentioning a variant name
 * or a function name cannot satisfy a check meant to find real code.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const source = stripComments(
  readFileSync(join(ROOT, "src/components/route-error.tsx"), "utf8"),
)

/** The full text of `function <name>(...)... { ... }` (arrow functions and
 * exports included, since `export function X(` still contains the literal
 * `function X(` marker this searches for), from its signature to its
 * matching closing brace. Throws — rather than returning an empty or
 * partial slice — when `name` can't be found or the braces don't balance,
 * so a rename in the source breaks this gate loudly instead of it silently
 * checking an empty string forever. */
function sliceFunction(name: string): string {
  const marker = `function ${name}(`
  const start = source.indexOf(marker)
  if (start === -1) throw new Error(`function ${name} not found in route-error.tsx`)

  const parenOpen = start + marker.length - 1
  let parenDepth = 0
  let afterParams = -1
  for (let i = parenOpen; i < source.length; i++) {
    if (source[i] === "(") parenDepth++
    else if (source[i] === ")") {
      parenDepth--
      if (parenDepth === 0) {
        afterParams = i + 1
        break
      }
    }
  }
  if (afterParams === -1) throw new Error(`unbalanced parens scanning ${name}'s parameter list`)

  const bodyOpen = source.indexOf("{", afterParams)
  let braceDepth = 0
  for (let j = bodyOpen; j < source.length; j++) {
    if (source[j] === "{") braceDepth++
    else if (source[j] === "}") {
      braceDepth--
      if (braceDepth === 0) return source.slice(start, j + 1)
    }
  }
  throw new Error(`unbalanced braces scanning ${name}'s body`)
}

describe("sliceFunction — the gate's own slicer, on a literal (not the real file)", () => {
  it("finds a function whose parameter list itself contains nested parens and braces", () => {
    const tricky = stripComments(`
      function Weird({ a, b }: { a: string; f: () => void }) {
        return a + b
      }
      function Other() {
        return null
      }
    `)
    const start = tricky.indexOf("function Weird(")
    const parenOpen = start + "function Weird(".length - 1
    let depth = 0
    let after = -1
    for (let i = parenOpen; i < tricky.length; i++) {
      if (tricky[i] === "(") depth++
      else if (tricky[i] === ")") {
        depth--
        if (depth === 0) {
          after = i + 1
          break
        }
      }
    }
    expect(after).toBeGreaterThan(-1)
    expect(tricky.slice(after, after + 20)).toContain("{")
  })
})

describe("route-error.tsx wiring (Finding 14)", () => {
  it("RouteErrorScreen (the top-level errorElement) renders only frame=\"standalone\"", () => {
    const body = sliceFunction("RouteErrorScreen")
    expect(body).toContain('renderFailure(failure, "standalone"')
    expect(body).not.toContain("portal")
  })

  it("PortalErrorFallback renders only frame=\"portal\"", () => {
    const body = sliceFunction("PortalErrorFallback")
    expect(body).toContain('renderFailure(failure, "portal"')
    expect(body).not.toContain("standalone")
  })

  it("service-trouble mounts useServiceHealth", () => {
    const body = sliceFunction("ServiceTroubleState")
    expect(body).toContain("useServiceHealth()")
  })

  it("chunk-load errors are never reported — useReportRouteError returns before reportClientError", () => {
    const body = sliceFunction("useReportRouteError")
    const guardAt = body.indexOf("isChunkLoadError(error)")
    const reportAt = body.indexOf("reportClientError(")
    expect(guardAt).toBeGreaterThan(-1)
    expect(reportAt).toBeGreaterThan(-1)
    expect(guardAt).toBeLessThan(reportAt)
  })

  it("classification is wired through the pure canReload predicate, not a side-effecting attemptReload shape", () => {
    expect(source).not.toContain("attemptReload")
    expect(sliceFunction("RouteErrorScreen")).toContain("canReload: canReloadChunkError")
    expect(sliceFunction("PortalErrorFallback")).toContain("canReload: canReloadChunkError")
  })

  it("the guarded reload (handleChunkError) is called exactly once in this file, from inside a useEffect", () => {
    const occurrences = source.split("handleChunkError(").length - 1
    expect(occurrences).toBe(1)

    const body = sliceFunction("useReloadInProgress")
    const effectAt = body.indexOf("useEffect(")
    const callAt = body.indexOf("handleChunkError(")
    expect(effectAt).toBeGreaterThan(-1)
    expect(callAt).toBeGreaterThan(-1)
    expect(effectAt).toBeLessThan(callAt)
  })

  it("neither exported component calls handleChunkError directly from its own (render) body", () => {
    expect(sliceFunction("RouteErrorScreen")).not.toContain("handleChunkError(")
    expect(sliceFunction("PortalErrorFallback")).not.toContain("handleChunkError(")
  })

  it("useReloadInProgress's escape hatch (SHOULD-FIX 6) clears its timer on cleanup and resets per render", () => {
    const body = sliceFunction("useReloadInProgress")
    expect(body).toContain("setStuck(true)")
    expect(body).toMatch(/return \(\) => window\.clearTimeout\(timer\)/)
    // Reset at the top of the effect, not only on the reloading branch — a
    // fresh error/failure pair must not inherit a stale `stuck: true` from
    // whatever was rendered before it.
    expect(body).toContain("setStuck(false)")
  })
})
