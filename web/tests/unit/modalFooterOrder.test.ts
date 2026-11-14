import { readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * The native Modal footer stacks its actions full-width and reverses the column, so a caller
 * that lists Cancel first and the confirm second gets the confirm on top. A caller whose FIRST
 * footer button is the primary or safe action already has the order it wants in the DOM (focus
 * lands on it first), and the reversal would put it at the bottom. Such a caller marks its
 * footer row `data-primary-first`, which stacks it in DOM order. This scan finds every Modal
 * `footer={...}` with two or more Buttons whose first Button is primary or accent and which
 * lacks the marker.
 */

const SRC = join(import.meta.dirname, "..", "..", "src")

function tsx(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, e.name)
    if (e.isDirectory()) tsx(full, out)
    else if (e.name.endsWith(".tsx")) out.push(full)
  }
  return out
}

/** The text of a `footer={...}` JSX expression, found by balancing braces. */
function footers(src: string): { text: string; line: number }[] {
  const out: { text: string; line: number }[] = []
  for (const m of src.matchAll(/\bfooter=\{/g)) {
    let depth = 1
    let i = (m.index ?? 0) + m[0].length
    const start = i
    while (i < src.length && depth > 0) {
      if (src[i] === "{") depth++
      else if (src[i] === "}") depth--
      i++
    }
    out.push({ text: src.slice(start, i - 1), line: src.slice(0, m.index).split("\n").length })
  }
  return out
}

export function footerOffenders(src: string): number[] {
  const bad: number[] = []
  for (const f of footers(src)) {
    // A ternary footer is two separate rows; judge each branch on its own.
    for (const branch of f.text.split(/\)\s*:\s*\(/)) {
      const tags = [...branch.matchAll(/<Button\b[^>]*>/g)].map((t) => t[0])
      if (tags.length < 2) continue
      if (!/variant="(?:primary|accent)"/.test(tags[0])) continue
      if (/data-primary-first/.test(branch)) continue
      bad.push(f.line)
    }
  }
  return bad
}

describe("Modal footers whose first button is the primary action are marked data-primary-first", () => {
  it("every caller", () => {
    const offenders: string[] = []
    for (const file of tsx(SRC)) {
      for (const line of footerOffenders(readFileSync(file, "utf8"))) offenders.push(`${relative(SRC, file)}:${line}`)
    }
    expect(offenders).toEqual([])
  })
  it("the scan itself catches an unmarked primary-first footer and accepts a marked one", () => {
    const bare = `<Modal footer={<div><Button variant="primary">Keep</Button><Button>Remove</Button></div>} />`
    expect(footerOffenders(bare)).toEqual([1])
    expect(footerOffenders(bare.replace("<div>", "<div data-primary-first>"))).toEqual([])
    expect(footerOffenders(`<Modal footer={<><Button variant="secondary">No</Button><Button variant="accent">Yes</Button></>} />`)).toEqual([])
  })
})
