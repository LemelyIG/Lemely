#!/usr/bin/env node
/*
 * Copy-rule checker for REDESIGN-MISSION §3.2 item 10, enforced as Hard Gate
 * §9.8.
 *
 * The mission bans em-dashes in UI copy outright ("restructure the sentence or
 * use a comma/period"). A one-off grep is not enough to enforce that, because
 * three visually similar things are not the same rule:
 *
 *   1. **Prose punctuation** — "Your XP is still counted — you are just…".
 *      This is what the ban is about, and this is what the script reports.
 *
 *   2. **The empty-value dash** — `{value ?? "—"}` in a table cell or stat.
 *      A typographic convention meaning "no data here", not a sentence. The
 *      mission's own remedy ("restructure the sentence or use a comma") has no
 *      meaning applied to it. Allowed, and deliberately so: replacing it with
 *      "N/A" or an empty cell would be a worse table, and replacing it with a
 *      hyphen would read as a minus sign next to numbers.
 *
 *   3. **En-dashes in ranges** — "70–79%", "12 May – 18 May". Correct
 *      typography for a span of values, and not prose punctuation either.
 *
 * So the check is narrow on purpose. A checker that flags all three is a
 * checker whose output gets ignored, which is worse than no checker.
 *
 * ── Rule 2: exclamation marks (REDESIGN-MISSION §3.2 item 10, DESIGN.md §12)
 *
 * The mission bans exclamation marks in product copy ("No exclamation marks
 * in success messages"; DESIGN.md §12's error-state rule is "active voice",
 * not "!"). `!` is also, constantly, not punctuation at all in this codebase:
 * `!==`, `!isValid`, `!!value`, a regex character class, and TypeScript's
 * non-null `value!` all use the same character for something a reader of the
 * UI never sees. So this rule only looks *inside* a string literal or a JSX
 * text node (the same two places rule 1 restricts itself to, for the same
 * reason: those are the only places a `!` is copy rather than code), and even
 * there it only counts a `!` that reads as sentence punctuation: one directly
 * followed by the string's closing quote, whitespace, `<` (a JSX text node
 * ending flush against the next tag), or the end of the line. That excludes
 * `!==` inside an example string, a literal `"!important"` CSS override, and
 * `!!x` written out as prose about code, all of which are followed by a
 * character (`=`, a letter) no real "Wait!" or "Reconnected!" ever is.
 *
 * Deliberately NOT attempted: detecting passive voice for the mission's
 * separate "active voice errors" rule. That is a judgement about grammar a
 * regex cannot make honestly — "was closed" is passive, "closed" can be a
 * past participle in an active clause, and a checker that guesses wrong half
 * the time teaches people to ignore it, same as rule 1's own reasoning above.
 * Passive voice belongs to code review, not this gate.
 *
 * Usage:
 *   node scripts/check_copy.mjs            # report, exit 1 if anything found
 *   node scripts/check_copy.mjs --count    # totals per file, always exit 0
 *
 * Scope is deliberately `src/`. Comments are stripped before matching, so a
 * dash or bang in a code comment (which no user reads, and which this
 * codebase's documentation style uses heavily) is not a finding.
 */

import { readFileSync } from "node:fs"
import { readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"

const ROOT = new URL("..", import.meta.url).pathname
const SRC = join(ROOT, "src")

/**
 * Every .tsx AND .ts under src/, recursively.
 *
 * P4.4 widened this from `.tsx` only, because a whole class of UI copy had
 * moved out of components and the gate never followed it. `correctionOutcome.ts`
 * (P4.2) and `friendOutcome.ts` (P4.4) exist specifically to hold sentences
 * shown to students, and every screen's `*Data.ts` module carries its empty and
 * error-state bodies. Extending the walk found **9 real em-dashes in
 * user-facing strings that no run of this gate had ever seen**, five of them on
 * surface 3, which had been reported clean.
 *
 * The reported total is therefore not comparable across this change: 64 under
 * the old scope, 67 under the new one. The count did not grow, the gate's
 * eyesight did.
 *
 * Same shape as D6.12's recorded lesson — a condition every harness shares is a
 * condition no harness tests. Here it was a file extension.
 */
function sourceFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full))
    else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) out.push(full)
  }
  return out.sort()
}

/**
 * Blank out block and line comments *without changing the line count*.
 *
 * A block comment is replaced by its own newlines rather than deleted, so
 * every reported line number still addresses the real file. Deleting them
 * instead — which this did in its first version — makes the checker report
 * positions that drift further from the truth the more documented a file is,
 * and this codebase comments heavily. The output was unusable for navigation.
 *
 * Crude by design: it does not parse, so a `//` inside a string literal (a URL,
 * say) would truncate that line early. That direction of error is safe here.
 * It can only hide a finding on a line containing a URL, never invent one.
 */
export function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/^(\s*)\/\/.*$/gm, "$1")
}

/**
 * Is this dash an empty-value placeholder rather than prose?
 *
 * The shapes that count as a placeholder, all of which mean "no data":
 *   ?? "—"        ?? "–"        : "—"        > — <        {"—"}
 * The test is that the dash is the *entire* string or JSX text node. Prose
 * always has words on at least one side of it inside the same literal.
 */
export function isPlaceholder(fragment) {
  return /^["'`]\s*[—–]\s*["'`]$/.test(fragment.trim())
}

/**
 * Is this an en-dash between two numeric-ish values, i.e. a range?
 * Matches "70–79", "{b.lower}–{b.upper}", "${b.lower}–${b.upper}".
 *
 * "Numeric-ish" has to include an interpolation, because most ranges in this
 * codebase are computed rather than literal. The trailing side must therefore
 * accept `${` as well as `{` and a digit — the first version accepted only the
 * latter two, so `${b.lower}–${b.upper}%` in QuizResults was reported as prose.
 * Caught by the unit test below, not by reading.
 */
export function isRange(line, index) {
  const before = line.slice(Math.max(0, index - 24), index)
  const after = line.slice(index + 1, index + 25)
  const numericBefore = /[\d}]\s*$/.test(before)
  const numericAfter = /^\s*(\$\{|\{|\d)/.test(after)
  return numericBefore && numericAfter
}

/**
 * Every prose em-dash in one file's source, as `{line, text}`.
 *
 * Exported and pure so the three judgement calls this gate encodes
 * (placeholder / range / prose) are unit-tested rather than trusted. A gate
 * whose classifier is only ever exercised by running it over the real tree
 * cannot be shown to reject the right things, only to produce some number.
 */
export function findEmDashes(source) {
  const findings = []
  const lines = stripComments(source).split("\n")

  lines.forEach((line, lineIndex) => {
    for (let i = 0; i < line.length; i += 1) {
      const char = line[i]
      if (char !== "—" && char !== "–") continue

      // Placeholder: the dash is alone inside its own quoted literal, or is
      // the whole of a JSX text node between tags.
      //
      // P4.5 widened both arms, because both were reporting real placeholders
      // as prose and the cure for that is a better classifier, not source
      // contorted to please one:
      //
      //  - The quoted arm required `quoted.length === 1`, so a line holding
      //    TWO placeholders was reported. `{a ?? "–"}/{b ?? "–"}` in the
      //    review queue is one row's "marks awarded out of maximum" with
      //    neither value known, which is as placeholder as it gets. The bound
      //    existed only because `indexOf` cannot locate the second match;
      //    scanning positions properly removes the need for it without
      //    loosening what counts as a placeholder.
      //  - The JSX arm looked for `>` and `<` within 12 characters on the SAME
      //    line, so a dash that a formatter had put on its own line was
      //    missed. A line whose entire trimmed content is a dash is never
      //    prose: prose needs words either side of it, and there are none on
      //    the line at all.
      let insidePlaceholder = false
      for (const match of line.matchAll(/(["'`])\s*[—–]\s*\1/g)) {
        if (!isPlaceholder(match[0])) continue
        if (i > match.index && i < match.index + match[0].length) {
          insidePlaceholder = true
          break
        }
      }
      if (insidePlaceholder) continue
      if (/>\s*[—–]\s*</.test(line.slice(Math.max(0, i - 12), i + 12))) continue
      if (/^[—–]$/.test(line.trim())) continue

      if (isRange(line, i)) continue

      findings.push({ line: lineIndex + 1, text: line.trim().slice(0, 120) })
      break // one finding per line is enough to send someone to it
    }
  })

  return findings
}

/**
 * Files allowed to keep a `!` the general rule would otherwise flag, each
 * with the reason it is not product copy. Checked as a path suffix against
 * `sourceFiles`'s `relative(ROOT, file)` output, so an entry here reads the
 * same as the paths the CLI report itself prints.
 *
 * Empty today: nothing under `src/` needs one (see the header's findings
 * paragraph below). Kept as a named export, not inlined into the CLI block,
 * so a future legitimate case — a literal example string quoting someone
 * else's "!" that the followed-by heuristic cannot tell from prose — has
 * somewhere to go without loosening the classifier itself.
 */
export const EXCLAMATION_ALLOWLIST = []

/**
 * One line's worth of "prose spans": the character ranges that are either
 * the inside of a quoted string literal, or a JSX text node sitting directly
 * between `>` and `<`. Only characters inside one of these count as copy for
 * `findExclamationMarks` — everything else on the line is code, where `!` is
 * an operator, and reading it as punctuation would be wrong.
 *
 * Line-based, like `stripComments` and `findEmDashes` above: it does not
 * parse, so a template literal that spans multiple lines is invisible to it.
 * That trades completeness for a checker whose output can be trusted one
 * line at a time, the same trade this file's header already makes for `//`
 * inside a string truncating a line early.
 *
 * A backtick literal's `${...}` interpolations are blanked (not treated as
 * prose) before scanning: `${value!}`'s non-null assertion is code sitting
 * inside a template string, not a sentence. Only *simple* (non-nested)
 * interpolations are blanked — `${a ?? b}`, not `${fn({ a: 1 })}` — which is
 * the same shape of limitation as the multi-line one above: a nested brace
 * inside an interpolation can hide a real `!` from this function, never
 * invent one, so the safe direction of error.
 */
export function proseSpans(line) {
  const blankInterpolations = (inner) =>
    inner.replace(/\$\{[^{}]*\}/g, (match) => " ".repeat(match.length))

  const spans = []
  for (const re of [/"(?:[^"\\]|\\.)*"/g, /'(?:[^'\\]|\\.)*'/g, /`(?:[^`\\]|\\.)*`/g]) {
    for (const match of line.matchAll(re)) {
      spans.push(blankInterpolations(match[0].slice(1, -1)))
    }
  }
  for (const match of line.matchAll(/>([^<>{]*)</g)) {
    spans.push(match[1])
  }
  return spans
}

/**
 * Every exclamation mark that reads as prose punctuation in one file's
 * source, as `{line, text}`. Same shape and the same reasoning as
 * `findEmDashes`: exported and pure so the classifier is unit-tested rather
 * than trusted, one finding per line.
 *
 * A `!` counts only when both of these hold:
 *   1. it sits inside a `proseSpans` range (a string literal's contents or a
 *      JSX text node) — never bare code, so `!isValid`, `!==`, `!!x` and a
 *      TypeScript non-null `x!` are never even examined.
 *   2. the character right after it, within that same span, is the end of
 *      the span (i.e. the original string's closing quote or the `<` that
 *      ended the JSX text node) or whitespace — the shape sentence
 *      punctuation actually has. `!==` inside a string, `!important` in a
 *      CSS-in-JS literal, and `!!x` written out in prose about code all fail
 *      this: the character after their `!` is `=` or a letter, never one a
 *      real "Wait!" or "Reconnected!" is followed by.
 */
export function findExclamationMarks(source) {
  const findings = []
  const lines = stripComments(source).split("\n")

  lines.forEach((line, lineIndex) => {
    const found = proseSpans(line).some((span) => {
      for (let i = 0; i < span.length; i += 1) {
        if (span[i] !== "!") continue
        const next = span[i + 1]
        if (next === undefined || /\s/.test(next)) return true
      }
      return false
    })
    if (found) findings.push({ line: lineIndex + 1, text: line.trim().slice(0, 120) })
  })

  return findings
}

/*
 * CLI entry, guarded.
 *
 * The unit suite imports the classifier above, and an unguarded module body
 * would mean that importing it walks the whole source tree and then calls
 * `process.exit` — which inside vitest terminates the runner mid-suite rather
 * than failing a test, so the damage would not even be legible as a failure.
 * Only a direct `node scripts/check_copy.mjs` runs the block below.
 */
const invokedDirectly =
  process.argv[1] !== undefined &&
  import.meta.url === new URL(`file://${process.argv[1]}`).href

if (invokedDirectly) {
  const emDashFindings = []
  const exclamationFindings = []
  for (const file of sourceFiles(SRC)) {
    const rel = relative(ROOT, file)
    const source = readFileSync(file, "utf8")
    for (const hit of findEmDashes(source)) {
      emDashFindings.push({ file: rel, ...hit })
    }
    if (!EXCLAMATION_ALLOWLIST.includes(rel)) {
      for (const hit of findExclamationMarks(source)) {
        exclamationFindings.push({ file: rel, ...hit })
      }
    }
  }

  if (process.argv.includes("--count")) {
    const perFile = new Map()
    for (const f of [...emDashFindings, ...exclamationFindings]) {
      perFile.set(f.file, (perFile.get(f.file) ?? 0) + 1)
    }
    const sorted = [...perFile.entries()].sort((a, b) => b[1] - a[1])
    for (const [file, count] of sorted) console.log(`${String(count).padStart(3)}  ${file}`)
    console.log(
      `\n${emDashFindings.length} em-dash line(s), ${exclamationFindings.length} ` +
        `exclamation-mark line(s), across ${perFile.size} files`,
    )
    process.exit(0)
  }

  if (emDashFindings.length === 0 && exclamationFindings.length === 0) {
    console.log("check_copy: no em-dashes or exclamation marks in UI copy.")
    process.exit(0)
  }

  if (emDashFindings.length > 0) {
    console.error(
      `check_copy: ${emDashFindings.length} em-dash(es) in UI copy (MISSION §3.2 item 10).`,
    )
    console.error("Restructure the sentence, or use a comma or a full stop.\n")
    for (const f of emDashFindings) {
      console.error(`  ${f.file}:${f.line}`)
      console.error(`    ${f.text}`)
    }
  }

  if (exclamationFindings.length > 0) {
    if (emDashFindings.length > 0) console.error("")
    console.error(
      `check_copy: ${exclamationFindings.length} exclamation mark(s) in UI copy ` +
        "(MISSION §3.2 item 10, DESIGN.md §12).",
    )
    console.error("Rewrite without the exclamation mark.\n")
    for (const f of exclamationFindings) {
      console.error(`  ${f.file}:${f.line}`)
      console.error(`    ${f.text}`)
    }
  }

  process.exit(1)
}
