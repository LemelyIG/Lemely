import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { sourceFiles, stripComments } from "./support/jsxSource"

/**
 * The lexer six gates read the product through (P7.1).
 *
 * It has its own test file because it is the single point of failure for every
 * tree-walking gate in this repo: `a11yRules`, `contrastRules`,
 * `elevationScale`, `adaptRules`, `motionDefaults` and `utilityExistence` all
 * decide what counts as code by asking it. A defect here does not make a gate
 * fail, it makes a gate *see less*, which is the one failure mode none of them
 * can report on themselves.
 *
 * The cases below are the ones that actually bit, kept verbatim.
 */

const SRC = join(import.meta.dirname, "..", "..", "src")

describe("comments are blanked", () => {
  it("blanks a line comment and keeps the offsets", () => {
    const raw = `const a = 1 // set a\nconst b = 2\n`
    const out = stripComments(raw)
    // Length, not a hand-counted run of spaces: offset preservation is the
    // property every gate depends on for its line numbers, and a fixture that
    // counts spaces by eye tests the fixture.
    expect(out.length).toBe(raw.length)
    expect(out).not.toContain("set a")
    expect(out.startsWith("const a = 1 ")).toBe(true)
    expect(out).toContain("const b = 2")
  })

  it("blanks a comment inside a template interpolation", () => {
    // `DeviceLimitNotice.tsx` does exactly this inside a className template.
    const raw = "const c = `border ${\n  // pick the firmer border\n  on ? 'a' : 'b'\n}`\n"
    const out = stripComments(raw)
    expect(out.length).toBe(raw.length)
    expect(out).not.toContain("pick the firmer border")
    expect(out).toContain("on ? 'a' : 'b'")
  })

  it("blanks a block comment and keeps its newlines, so line numbers stay true", () => {
    const out = stripComments(`a\n/* one\n   two */\nb\n`)
    expect(out.split("\n").length).toBe(5)
    expect(out).not.toContain("one")
    expect(out).not.toContain("two")
  })

  it("does not treat a comment marker inside a string as a comment", () => {
    const out = stripComments(`const url = "https://example.com/x"\nconst after = 1\n`)
    expect(out).toContain("https://example.com/x")
    expect(out).toContain("const after = 1")
  })
})

describe("an apostrophe in JSX text is text, not a string delimiter", () => {
  /*
   * The defect this file was written for. `Couldn't` opened a string that ran
   * until the next stray apostrophe anywhere below, and every comment in
   * between survived comment-stripping and was scanned as code.
   */
  it("does not open a string on the apostrophe in the product's own error copy", () => {
    const source = [
      `<div>`,
      `  Couldn't create the class: {message}`,
      `  // a comment that must still be blanked`,
      `  <button onClick={go}>Go</button>`,
      `</div>`,
    ].join("\n")
    const out = stripComments(source)
    expect(out).not.toContain("a comment that must still be blanked")
    expect(out).toContain("<button onClick={go}>")
  })

  it("handles the exact pair that desynchronised Classes.tsx", () => {
    // "Couldn't" on one line, `axe's` inside a comment eighteen lines below.
    // Before the fix, everything between them was read as string content.
    const source = [
      `      Couldn't create the class: {m}`,
      `      // scroll is axe's serious rule. Do not strip these.`,
      `      const marker = 1`,
    ].join("\n")
    const out = stripComments(source)
    expect(out).not.toContain("axe")
    expect(out).toContain("const marker = 1")
  })

  it("still lexes real string literals, including ones holding an apostrophe", () => {
    const out = stripComments(`const s = 'it\\'s fine' // gone\nconst t = "it's fine" // gone\nx`)
    expect(out).toContain(`'it\\'s fine'`)
    expect(out).toContain(`"it's fine"`)
    expect(out).not.toContain("gone")
    expect(out.trimEnd().endsWith("x")).toBe(true)
  })

  it("opens a string where one can legally begin", () => {
    // Each quote here follows `(`, `=`, `,` or whitespace, so each is a real
    // delimiter and the trailing comment must be blanked.
    const out = stripComments(`f('a', "b", \`c\`) // gone\n`)
    expect(out).not.toContain("gone")
    expect(out).toContain(`f('a', "b", \`c\`)`)
  })
})

describe("the whole product lexes cleanly", () => {
  /*
   * The regression that matters most: not "does one case work" but "does any
   * file in the product still desynchronise". A file whose lexer ends mid-
   * string has an unscanned tail, and no gate reading it would say so.
   */
  it("no .tsx file ends the scan inside a string or leaves comment text standing", () => {
    const offenders: string[] = []
    for (const file of sourceFiles(SRC)) {
      const raw = readFileSync(file, "utf8")
      const out = stripComments(raw)
      const survivingComment = out.match(/^[ \t]*\/\/[ \t]\S/m)
      if (survivingComment) {
        offenders.push(`${file} — a line comment survived stripping`)
      }
      // Offsets must be preserved exactly, or every reported line number and
      // every `index` a gate hands back points at the wrong place.
      if (out.length !== raw.length) {
        offenders.push(`${file} — length changed ${raw.length} to ${out.length}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
