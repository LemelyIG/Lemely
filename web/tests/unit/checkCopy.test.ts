import { describe, expect, it } from "vitest"

// @ts-expect-error — plain .mjs gate script, no type declarations by design.
import { findEmDashes, isPlaceholder, isRange, stripComments } from "../../scripts/check_copy.mjs"

/*
 * P3.3 · the copy gate's own classifier.
 *
 * `check_copy.mjs` enforces MISSION §3.2 item 10 (no em-dashes in UI copy) as
 * Hard Gate §9.8, and Phase 4 will lean on it surface by surface. It encodes
 * three judgement calls, not one rule:
 *
 *   - prose punctuation is a finding,
 *   - the empty-value dash in a table cell (`{value ?? "—"}`) is not,
 *   - an en-dash between numbers ("70–79%") is not.
 *
 * A gate whose classifier is exercised only by running it across the real tree
 * can be shown to produce *a* number, never the right one. These tests pin
 * both directions: what it must catch, and what it must leave alone. The
 * second matters more — a checker that cries wolf on every table cell is a
 * checker whose output gets ignored, which is worse than having none.
 */

const find = (source: string) => findEmDashes(source) as { line: number; text: string }[]

describe("stripComments", () => {
  /*
   * This codebase documents heavily, and its comments are full of em-dashes.
   * Flagging those would bury every real finding, so comments are blanked.
   */
  it("ignores an em-dash inside a line comment", () => {
    expect(find('// this — is a comment\nconst a = 1')).toHaveLength(0)
  })

  it("ignores an em-dash inside a block comment", () => {
    expect(find('/*\n * prose — with a dash\n */\nconst a = 1')).toHaveLength(0)
  })

  /*
   * The reason this function blanks rather than deletes. The checker's first
   * version removed comment lines outright, so every reported line number
   * drifted by the size of the comments above it and pointed at the wrong
   * place in the real file.
   */
  it("preserves line numbers so findings address the real file", () => {
    const source = ['/*', ' * a comment — with a dash', ' */', '', '<p>Real — copy</p>'].join("\n")
    expect(stripComments(source).split("\n")).toHaveLength(5)
    expect(find(source)[0].line).toBe(5)
  })
})

describe("prose em-dashes are findings", () => {
  it.each([
    ["<p>Your XP is still counted — you are just hidden.</p>"],
    ['const msg = "Couldn\'t save — try again."'],
    ['<Empty body="Nothing is wrong — this is a connection problem." />'],
    ["Offline — answers save locally"],
  ])("flags %s", (source) => {
    expect(find(source)).toHaveLength(1)
  })

  it("reports one finding per line, not one per character", () => {
    expect(find("A — b — c — d")).toHaveLength(1)
  })

  it("finds nothing in copy that already obeys the rule", () => {
    expect(find("<p>We couldn't save that change. Try again.</p>")).toHaveLength(0)
  })
})

describe("the empty-value dash is not a finding", () => {
  it.each([
    ['{value ?? "—"}'],
    ['{c.average != null ? `${c.average}%` : "—"}'],
    ['<span className="text-t3">—</span>'],
    ['{q.topic ?? "—"}'],
  ])("allows %s", (source) => {
    expect(find(source)).toHaveLength(0)
  })

  it("classifies a lone quoted dash as a placeholder", () => {
    expect(isPlaceholder('"—"')).toBe(true)
    expect(isPlaceholder("' – '")).toBe(true)
  })

  /*
   * The boundary that matters: a dash with words beside it inside the same
   * literal is prose, however short. Getting this wrong in the permissive
   * direction would silently exempt real copy from the gate.
   */
  it("does not classify prose as a placeholder", () => {
    expect(isPlaceholder('"You — 5/8"')).toBe(false)
    expect(find('<span>You — {score}/{max}</span>')).toHaveLength(1)
  })
})

describe("en-dashes in ranges are not findings", () => {
  it.each([
    ["const label = `${b.lower}–${b.upper}%`"],
    ["<span>70–79%</span>"],
  ])("allows %s", (source) => {
    expect(find(source)).toHaveLength(0)
  })

  it("recognises a numeric range by its neighbours", () => {
    const line = "70–79"
    expect(isRange(line, line.indexOf("–"))).toBe(true)
  })

  it("does not treat a dash between words as a range", () => {
    const line = "marks — they've"
    expect(isRange(line, line.indexOf("—"))).toBe(false)
  })
})
