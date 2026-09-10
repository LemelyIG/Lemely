import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Packet A7 — gated service-worker activation.
 *
 * D5.15's original `self.skipWaiting()` ran unconditionally on install,
 * which is the "silent update swap" ledger finding: a new worker took
 * control (and, combined with `registerType: "autoUpdate"`, silently
 * reloaded every open tab) with no user consent, possibly mid-interaction.
 * `useServiceWorkerUpdate` now gates that on an explicit "Reload" click,
 * which needs the worker to stay in `waiting` until it is told to skip —
 * the only way to tell it that from the page is `postMessage`, so this test
 * pins that `self.skipWaiting()` is reachable *only* from a message
 * listener, source-text style (the same pattern `useCountdown.test.ts` and
 * others already use for a service worker/effect body this suite's
 * jsdom-less environment cannot otherwise exercise, D3.20).
 */

const source = readFileSync(join(import.meta.dirname, "..", "..", "src", "sw.ts"), "utf8")

/**
 * Extracts the full `self.addEventListener("message", ... )` call, brace
 * pair and all, by counting braces from the opening `{` rather than a
 * non-greedy regex — the listener's body nests a `.catch(() => { ... })`,
 * and `[\s\S]*?\}\)` stops at that inner closer, not the outer one.
 */
function extractMessageListener(text: string): string | null {
  const startMatch = text.match(/self\.addEventListener\("message",\s*\([^)]*\)\s*=>\s*\{/)
  if (!startMatch || startMatch.index === undefined) return null
  const bodyStart = startMatch.index + startMatch[0].length
  let depth = 1
  let i = bodyStart
  while (i < text.length && depth > 0) {
    if (text[i] === "{") depth += 1
    else if (text[i] === "}") depth -= 1
    i += 1
  }
  if (depth !== 0) return null
  // `i` now sits just past the matching `}`; the call still needs its own
  // closing `)`.
  const closeParen = text.indexOf(")", i)
  if (closeParen === -1) return null
  return text.slice(startMatch.index, closeParen + 1)
}

describe("sw.ts — gated skip-waiting (A7)", () => {
  const listener = extractMessageListener(source)

  it("has a message listener that skips waiting on SKIP_WAITING", () => {
    expect(listener, 'no self.addEventListener("message", ...) block found').not.toBeNull()
    expect(listener).toMatch(/SKIP_WAITING/)
    expect(listener).toMatch(/self\.skipWaiting\(\)/)
  })

  it("never calls self.skipWaiting() outside that message listener", () => {
    expect(listener).not.toBeNull()
    const withoutMessageListener = listener ? source.replace(listener, "") : source
    expect(withoutMessageListener).not.toMatch(/self\.skipWaiting\(\)/)
  })

  it("still claims clients unconditionally — only activation waits on consent, not control of already-open tabs once activated", () => {
    expect(source).toMatch(/^clientsClaim\(\)/m)
  })
})
