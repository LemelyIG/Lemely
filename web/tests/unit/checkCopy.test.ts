import { describe, expect, it } from "vitest"

import {
  findEmDashes,
  findExclamationMarks,
  isPlaceholder,
  isRange,
  proseSpans,
  stripComments,
  // @ts-expect-error — plain .mjs gate script, no type declarations by design.
} from "../../scripts/check_copy.mjs"

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

/*
 * P4.5 widened two placeholder arms. Both widenings are pinned in the
 * permissive AND the strict direction, because the failure mode of a
 * classifier change is silently exempting real copy — which is the one thing
 * this gate exists to stop.
 */
describe("placeholder arms widened by P4.5", () => {
  it("allows two placeholder dashes on one line", () => {
    // The review queue's "marks awarded out of maximum" with neither value
    // known. The old classifier bailed out whenever a line held more than one
    // quoted dash, so this real placeholder was reported as prose.
    expect(find('<td>{item.awarded ?? "–"}/{item.maximum ?? "–"}</td>')).toHaveLength(0)
  })

  it("still reports prose on a line that also holds a placeholder", () => {
    // The widening must not become "a line containing any placeholder is
    // exempt". The dash between words here is prose and has to survive.
    expect(
      find('<td>{a ?? "–"} — and the rest of this is a real sentence</td>'),
    ).toHaveLength(1)
  })

  it("allows a dash that a formatter put on its own line", () => {
    // The JSX arm looked for `>` and `<` within 12 characters on the same
    // line, so a wrapped element hid its own placeholder from the exemption.
    const source = ['<div', '  aria-label="No data"', '>', '  –', '</div>'].join("\n")
    expect(find(source)).toHaveLength(0)
  })

  it("does not exempt a lone dash that has words on the same line", () => {
    expect(find("  Nothing here — try again")).toHaveLength(1)
  })
})

/*
 * P5.x · exclamation marks (REDESIGN-MISSION §3.2 item 10, DESIGN.md §12).
 *
 * Same shape of test as the em-dash suite above: pin what the rule must
 * catch, and — more importantly — what it must leave alone, since `!` is an
 * ordinary operator character constantly present in real code (`!==`,
 * `!isValid`, `!!value`, a non-null assertion, a regex class, `!important`).
 */
const findBangs = (source: string) => findExclamationMarks(source) as { line: number; text: string }[]

describe("exclamation marks in UI copy are findings", () => {
  it.each([
    ['<p>Nice work!</p>'],
    ['const msg = "Reconnected!"'],
    ['<Empty body="You are all caught up!" />'],
    ["<p>Wait!</p>"],
  ])("flags %s", (source) => {
    expect(findBangs(source)).toHaveLength(1)
  })

  it("reports one finding per line, not one per character", () => {
    expect(findBangs('<p>Wow! Great! Amazing!</p>')).toHaveLength(1)
  })

  it("finds nothing in copy that already obeys the rule", () => {
    expect(findBangs("<p>Nice work.</p>")).toHaveLength(0)
  })
})

describe("exclamation marks in code are not findings", () => {
  it.each([
    ["if (!isValid) return"],
    ["const ready = !!value"],
    ["const label = value!"],
    ['const re = /[!?]/'],
    ['const css = "font-weight: bold !important;"'],
    ["// don't forget this!"],
    ["/* remember! */"],
  ])("allows %s", (source) => {
    expect(findBangs(source)).toHaveLength(0)
  })

  it("does not flag a non-null assertion inside a template interpolation", () => {
    expect(findBangs('const msg = `Score: ${value!}`')).toHaveLength(0)
  })
})

/*
 * Adversarial review SHOULD-FIX 9: `proseSpans` only ever matched a JSX text
 * node when `>` and `<` sat on the same line, so prettier-wrapped copy (the
 * dominant shape in this codebase) was invisible to the gate. These pin the
 * fix: a wrapped text node is now found via the whole-file `jsxTextSpans`
 * pass, and the FPs that reproduced alongside it (a bare comparison read as
 * markup, and two non-prose strings) are excluded.
 */
describe("wrapped JSX text nodes (SHOULD-FIX 9)", () => {
  it("flags a multi-line JSX text node with words before the exclamation mark", () => {
    const source = ["<p>", "  You're offline! Answers save locally.", "</p>"].join("\n")
    const findings = findBangs(source)
    expect(findings).toHaveLength(1)
    expect(findings[0].line).toBe(2)
  })

  it("flags a JSX text node that is the exclamation-marked sentence entirely", () => {
    const source = ["<p>", "  Nice work!", "</p>"].join("\n")
    const findings = findBangs(source)
    expect(findings).toHaveLength(1)
    expect(findings[0].line).toBe(2)
  })

  it("flags a wrapped-line text node with the open and close tags on other lines", () => {
    const source = ["<Empty", '  title="Done"', ">", "  Nice work!", "</Empty>"].join("\n")
    const findings = findBangs(source)
    expect(findings).toHaveLength(1)
    expect(findings[0].line).toBe(4)
  })

  it("does not report a wrapped JSX text node twice", () => {
    // The per-line pass and the whole-file pass can both see a node that
    // happens to fit on one line; the merge must not double-count it.
    expect(findBangs("<p>Nice work!</p>")).toHaveLength(1)
  })
})

describe("false positives found alongside SHOULD-FIX 9", () => {
  it("does not read a bare comparison as a JSX text node", () => {
    expect(findBangs("if (a > 0 && ! b && c < 3) {}")).toHaveLength(0)
  })

  it("does not treat a shell-command string as prose", () => {
    expect(findBangs("const cmd = \"grep -v '! ' file\"")).toHaveLength(0)
  })

  it("does not treat a className value as prose", () => {
    expect(findBangs('className="flex ! mt-0"')).toHaveLength(0)
  })
})

describe("proseSpans", () => {
  it("extracts a quoted string literal's contents", () => {
    expect(proseSpans('const msg = "Reconnected!"')).toContain("Reconnected!")
  })

  it("extracts a JSX text node's contents", () => {
    expect(proseSpans("<p>Nice work!</p>")).toContain("Nice work!")
  })

  it("blanks a simple template interpolation rather than exposing it as prose", () => {
    const spans = proseSpans('const msg = `Score: ${value!}`')
    expect(spans.some((s: string) => s.includes("!"))).toBe(false)
  })
})

describe("text on either side of an interpolation is still copy (verification residual)", () => {
  it.each([
    ["<p>Great news! {confident} of {total}</p>"],
    ["<p>{count} paper{count === 1 ? \"\" : \"s\"} marked! Nice</p>"],
    ["<p>\n  You got {score} right!\n</p>"],
    ["<p>Done {fn({ a: 1 })}! Nested braces</p>"],
  ])("flags %s", (source) => {
    expect(findBangs(source)).toHaveLength(1)
  })

  it("does not read a non-null assertion inside an interpolation as punctuation", () => {
    expect(findBangs("<p>{value!}</p>")).toHaveLength(0)
    expect(findBangs("<p>Score {value!} today</p>")).toHaveLength(0)
  })
})

describe("aria attributes: spoken ones are copy, referential ones are not", () => {
  it.each([
    ['<button aria-label="Close this!" />'],
    ['<input aria-description="Type your answer!" />'],
    ['<span aria-roledescription="Slide!" />'],
  ])("flags %s", (source) => {
    expect(findBangs(source)).toHaveLength(1)
  })

  it.each([
    ['<div aria-labelledby="heading-one!" />'],
    ['<div aria-controls="panel! one" />'],
    ['<div aria-describedby="note! x" />'],
  ])("allows %s", (source) => {
    expect(findBangs(source)).toHaveLength(0)
  })
})
