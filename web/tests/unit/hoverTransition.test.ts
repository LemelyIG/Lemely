import { readFileSync, readdirSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * The snapping-hover gate (P5.1).
 *
 * DESIGN.md §9.2 is specific about the smallest piece of motion in the product:
 * "Press: `scale(0.98)` over `dur-fast`. Hover: a colour or 1px translate shift
 * over `dur-instant`." An element that changes colour on hover with no
 * `transition-*` utility does not do that. It snaps, in one frame, and the
 * interface reads as slightly cheap for a reason no one can point at.
 *
 * **Why this needs a gate rather than a sweep.** It is invisible from every
 * automated direction. The classes are all real and all resolve
 * (`utilityExistence` is happy), the values are all tokens (the token gate is
 * happy), the easing is never the banned one because there is no easing at all
 * (`motionDefaults` is happy), and a screenshot of a hover state looks
 * identical whether it arrived over 120ms or over 0ms. Only the transition
 * between two frames is wrong, and nothing in this repo looks at that.
 *
 * P5.1's sweep found 26 of these across the teacher portal, the admin portal,
 * onboarding and four kit components. They are not a style preference: they are
 * the one motion rule DESIGN.md states in units, unimplemented.
 *
 * **How the check avoids being a false-positive machine.** A naive line-based
 * grep is useless here, because `cn()` and `cva()` calls span many lines and
 * the `transition-*` class routinely sits on a different line from the
 * `hover:*` it governs — `Button`'s base has the transition and its variants
 * have the hovers, twelve lines apart, and it is entirely correct. So this
 * parses *balanced class-expression groups* (`cn(...)`, `cva(...)`, or a plain
 * `className="..."`) and asks whether the group that introduces a moving hover
 * also carries a transition anywhere inside it.
 *
 * A bare `transition-colors` is the right fix and needs no duration: P4.6 set
 * `--default-transition-duration` to `dur-instant` and
 * `--default-transition-timing-function` to `ease-out-soft` precisely so the
 * plain idiom is correct by default (D4.6). Do not add an explicit duration
 * unless §9.1 calls for a different rung.
 */

const ROOT = join(import.meta.dirname, "..", "..")

/**
 * A hover/active/group-hover that changes a property a transition can animate.
 *
 * Deliberately not every `hover:` — `hover:underline`, `hover:cursor-pointer`
 * and `hover:z-10` are not animatable and demanding a transition for them would
 * be noise. Colour, opacity, transform and shadow are.
 */
const MOVING_STATE =
  /(?:hover|active|group-hover):(?:bg-|text-|border-|opacity-|translate-|scale-|shadow-)/

/**
 * Files exempt from the rule, each with its reason.
 *
 * Kept deliberately short. An exemption is a claim that an element should snap,
 * and there are very few honest ones.
 */
const EXEMPT = new Map<string, string>([
  [
    "src/components/ui/nav-shells.tsx",
    // Build-era shell, superseded by `portals/*/index.tsx` and the Phase 3
    // `NavDrawer`. It is not on any migration list and no screen renders it;
    // Phase 6's compat-layer closeout is where it goes, not here.
    "build-era shell with no call site; retired in Phase 6",
  ],
])

function sourceFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith(".tsx")) out.push(full)
    }
  }
  walk(join(ROOT, "src"))
  return out
}

/**
 * Every balanced class-expression group in a source file.
 *
 * `cn(`/`cva(`/`buttonVariants(` are matched by walking parentheses rather than
 * by a regex, so a nested call or a template literal inside the argument list
 * cannot end the group early — which is the whole reason the naive version of
 * this check reported `Button` as broken.
 */
function classGroups(src: string): { text: string; index: number }[] {
  const out: { text: string; index: number }[] = []
  const opener = /\b(?:cn|cva|buttonVariants)\s*\(/g
  let match: RegExpExecArray | null
  while ((match = opener.exec(src)) !== null) {
    let depth = 1
    let i = opener.lastIndex
    while (i < src.length && depth > 0) {
      if (src[i] === "(") depth++
      else if (src[i] === ")") depth--
      i++
    }
    out.push({ text: src.slice(match.index, i), index: match.index })
  }
  for (const plain of src.matchAll(/className="([^"]*)"/g)) {
    out.push({ text: plain[1], index: plain.index ?? 0 })
  }
  return out
}

function lineOf(src: string, index: number): number {
  return src.slice(0, index).split("\n").length
}

describe("a hover that changes colour also transitions to it", () => {
  it("has no element that snaps between two states", () => {
    const offenders: string[] = []

    for (const file of sourceFiles()) {
      const relative = pathRelative(ROOT, file).split("\\").join("/")
      if (EXEMPT.has(relative)) continue
      const src = readFileSync(file, "utf8")
      for (const group of classGroups(src)) {
        if (!MOVING_STATE.test(group.text)) continue
        if (/\btransition/.test(group.text)) continue
        offenders.push(`${relative}:${lineOf(src, group.index)}`)
      }
    }

    expect(offenders).toEqual([])
  })
})
