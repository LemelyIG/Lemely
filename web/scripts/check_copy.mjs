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
 * followed by the string's closing quote, whitespace (including a line break
 * inside a wrapped JSX text node), `<` (a JSX text node ending flush against
 * the next tag), or the end of the line. That excludes `!==` inside an
 * example string, a literal `"!important"` CSS override, and `!!x` written
 * out as prose about code, all of which are followed by a character (`=`, a
 * letter) no real "Wait!" or "Reconnected!" ever is.
 *
 * What "inside a string literal or a JSX text node" covers, precisely,
 * because it is two different scans stitched together (`proseSpans` /
 * `jsxTextSpans`, both below) rather than one:
 *
 *   - A quoted string literal (`"`, `'`, or `` ` ``) is scanned per line —
 *     so a template literal that itself spans multiple lines is NOT
 *     covered, same limitation `stripComments` already has for `//`. A
 *     string that is a `className`/`class`/`href`/`src`/`style`/`aria-*`/
 *     `id` attribute's value, or of any `aria-*` attribute that names an
 *     element rather than describing it (`aria-labelledby`, `aria-controls`;
 *     `aria-label`, `aria-description`, `aria-placeholder`,
 *     `aria-roledescription` and `aria-valuetext` are prose a screen reader
 *     speaks, and stay covered), or that looks like a shell command
 *     (`"grep -v '! ' file"`), is excluded: none of those is prose, however
 *     much it may contain a `!` shaped like punctuation.
 *   - A JSX text node — the text directly between `>` and `<`, with any
 *     `{...}` expression child blanked out but the text on either side of it
 *     kept — IS covered whether it sits on one line or
 *     prettier has wrapped it across several, e.g.
 *     `<p>\n  Nice work!\n</p>`. The whole comment-stripped file is scanned
 *     for these, not one line at a time, specifically so a wrapped text
 *     node (the dominant shape of copy in this codebase) is not invisible
 *     to the gate. A `>`/`<` pair only counts as a text node's boundaries
 *     when the `>` is immediately preceded by a tag-like character
 *     (`[A-Za-z0-9_"'}/]`) and the `<` is immediately followed by `/` or a
 *     letter — so a bare comparison like `a > 0 && ! b && c < 3` is never
 *     mistaken for markup.
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
 * A JSX-attribute name whose *value* is markup/config, never prose — a
 * `className=`/`style=`/`href=`/`aria-*` string is data for the browser or
 * the router, not a sentence a reader sees. Checked against the text on the
 * line immediately before a candidate string literal's opening quote.
 */
const ATTRIBUTE_VALUE =
  /\b(?:className|class|href|src|style|id|aria-(?!label\b|description\b|placeholder\b|roledescription\b|valuetext\b)[\w-]+)\s*=\s*$/i

/**
 * Does this string look like a shell command / flag list rather than prose?
 * A cheap shape test, not a parser: a hyphen immediately followed by a
 * letter, itself preceded by start-of-string, whitespace, or a quote (` -v`,
 * `--verbose`, `'-x'`). Prose almost never puts a bare letter right after a
 * hyphen like that; a CLI example string constantly does.
 */
function looksLikeShellFlags(text) {
  return /(?:^|[\s"'])-{1,2}[A-Za-z]/.test(text)
}

/**
 * One line's worth of "prose spans": the character ranges that are either
 * the inside of a quoted string literal, or a JSX text node sitting directly
 * between `>` and `<`. Only characters inside one of these count as copy for
 * `findExclamationMarks` — everything else on the line is code, where `!` is
 * an operator, and reading it as punctuation would be wrong.
 *
 * Line-based, like `stripComments` and `findEmDashes` above: it does not
 * parse, so a template literal that spans multiple lines is invisible to it.
 * (A JSX text node that spans multiple lines is NOT invisible: see
 * `jsxTextSpans` below, which `findExclamationMarks` runs over the whole
 * file separately from this per-line function, precisely because prettier
 * wraps most real copy in this codebase onto its own line between an open
 * and a close tag.) That trades completeness for a checker whose output can
 * be trusted one line at a time, the same trade this file's header already
 * makes for `//` inside a string truncating a line early.
 *
 * A backtick literal's `${...}` interpolations are blanked (not treated as
 * prose) before scanning: `${value!}`'s non-null assertion is code sitting
 * inside a template string, not a sentence. Only *simple* (non-nested)
 * interpolations are blanked — `${a ?? b}`, not `${fn({ a: 1 })}` — which is
 * the same shape of limitation as the multi-line one above: a nested brace
 * inside an interpolation can hide a real `!` from this function, never
 * invent one, so the safe direction of error.
 *
 * Two guards keep this from reading code as copy:
 *
 *  - A quoted span that is a `className`/`href`/`style`/`aria-*`/... value,
 *    or that looks like a shell command (`"grep -v '! ' file"`), is not
 *    prose and is skipped. Both are shapes, not a parse, so both can be
 *    fooled by a deliberately adversarial literal; neither can be fooled by
 *    ordinary code, which is the bar this file's header sets throughout.
 *  - A `>`...`<` JSX span only counts when the `>` is immediately preceded
 *    by a tag-like character (`[A-Za-z0-9_"'}/]` — a tag name, an
 *    attribute's closing quote, `}` closing an attribute expression, or `/`
 *    of a self-closing tag) and the `<` is immediately followed by `/` or a
 *    letter (a closing tag or the next element). A comparison operator's
 *    `>` is preceded by whitespace and its `<` is followed by whitespace or
 *    a digit, so `if (a > 0 && ! b && c < 3)` no longer reads as a JSX text
 *    node.
 */
export function proseSpans(line) {
  const blankInterpolations = (inner) =>
    inner.replace(/\$\{[^{}]*\}/g, (match) => " ".repeat(match.length))

  const spans = []
  const consumed = [] // [start, end) ranges already claimed by a string literal
  for (const re of [/"(?:[^"\\]|\\.)*"/g, /'(?:[^'\\]|\\.)*'/g, /`(?:[^`\\]|\\.)*`/g]) {
    for (const match of line.matchAll(re)) {
      const start = match.index
      const end = start + match[0].length
      // A quote character of one kind sitting inside a literal of another
      // kind (`"grep -v '! ' file"`) is not a second, nested string literal —
      // it is just a character. Without this, the inner `'! '` would be
      // matched a second time as its own (bogus) single-quoted span.
      //
      // Only a match FULLY nested inside an already-consumed range is
      // dropped, not any overlap: a backtick literal containing a double
      // quote (`` `She said "hi"` ``) matches `"hi"` first (this loop tries
      // `"`, then `'`, then `` ` ``, in that order) and the backtick match
      // that follows CONTAINS that smaller range rather than sitting inside
      // it, so it is kept — the template literal's prose is not lost to
      // reject a match that is not actually a duplicate.
      if (consumed.some(([cs, ce]) => start >= cs && end <= ce)) continue
      consumed.push([start, end])

      const inner = match[0].slice(1, -1)
      if (!/[A-Za-z]/.test(inner)) continue
      if (ATTRIBUTE_VALUE.test(line.slice(0, start))) continue
      if (looksLikeShellFlags(inner)) continue

      spans.push(blankInterpolations(inner))
    }
  }
  for (const match of line.matchAll(/>([^<>{]*)</g)) {
    const text = match[1]
    if (text.trim() === "" || !/[A-Za-z]/.test(text)) continue
    const before = line[match.index - 1]
    if (before === undefined || !/[A-Za-z0-9_"'}/]/.test(before)) continue
    const after = line[match.index + 1 + text.length + 1]
    if (after === undefined || !/[/A-Za-z]/.test(after)) continue
    spans.push(text)
  }
  return spans
}

/**
 * Absolute character offsets of every line break in `source`, offset 0
 * included as the start of line 1. Built once per file so `lineForOffset`
 * below can turn an absolute offset from `jsxTextSpans` into a 1-based line
 * number by binary search instead of a linear rescan per offset.
 */
function lineStartOffsets(source) {
  const offsets = [0]
  for (let i = 0; i < source.length; i += 1) {
    if (source[i] === "\n") offsets.push(i + 1)
  }
  return offsets
}

/** 1-based line number containing absolute character offset `offset`. */
function lineForOffset(lineStarts, offset) {
  let lo = 0
  let hi = lineStarts.length - 1
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (lineStarts[mid] <= offset) lo = mid
    else hi = mid - 1
  }
  return lo + 1
}

/**
 * Every JSX text node in the WHOLE (comment-stripped) file, as
 * `{start, text}` where `start` is the absolute offset of `text`'s first
 * character. Unlike `proseSpans`, this is not line-based, which is the
 * point of it: prettier wraps the dominant shape of copy in this codebase
 * onto its own line —
 *
 *   <p>
 *     Nice work!
 *   </p>
 *
 * — and a line-at-a-time `>`...`<` match never sees it, because neither the
 * `>` nor the `<` is on the line with the text. Scanning the whole file with
 * the `s` flag closes that gap: the text-node match can cross newlines, and
 * `findExclamationMarks` below maps each finding's offset back to the real
 * line via `lineForOffset`.
 *
 * `[^<>{}]*` excludes `}` as well as `{` (the per-line `proseSpans` only
 * excludes `{`) so an expression child like `<p>{count} left</p>` does not
 * pull `{count}` into the span, and a stray `}` from a wrapped expression
 * a few lines up can't extend a match past where its own children end.
 *
 * Same tag-like guard as `proseSpans`'s JSX arm on the `>` — a bare
 * comparison such as `a > 0 && c < 3` must not read as markup just because
 * this function no longer confines itself to one line to find it — with one
 * addition this function needs and the per-line one does not: prettier
 * commonly wraps a multi-prop opening tag as
 *
 *   <Empty
 *     title="Done"
 *   >
 *
 * putting the closing `>` alone on its own line, preceded by a newline (or
 * indentation) rather than a tag-like character. A `>` that is the first
 * non-whitespace thing on its physical line is accepted on that basis alone
 * — real code does not leave a bare comparison operator dangling as the
 * only thing on a line, so this cannot readmit the `a > 0` shape above,
 * which always has its operand immediately to the left on the same line.
 */
export function jsxTextSpans(strippedSource) {
  const spans = []
  for (const match of strippedSource.matchAll(/>([^<>]*)</gs)) {
    // A `{...}` expression child is code, not copy, but the text on either
    // side of it is still the same text node (`Great news! {n} of {total}`),
    // so the interpolation is blanked in place rather than the whole node
    // being skipped. Nested braces (`{fn({ a: 1 })}`) are blanked from the
    // inside out; an unbalanced `{` is left alone and simply never counts as
    // sentence punctuation on its own.
    const text = blankBraces(match[1])
    if (text.trim() === "" || !/[A-Za-z]/.test(text)) continue

    const openIndex = match.index
    const lineStart = strippedSource.lastIndexOf("\n", openIndex - 1) + 1
    const standaloneOnLine = strippedSource.slice(lineStart, openIndex).trim() === ""
    const before = strippedSource[openIndex - 1]
    const beforeOk = standaloneOnLine || (before !== undefined && /[A-Za-z0-9_"'}/]/.test(before))
    if (!beforeOk) continue

    const closeIndex = openIndex + 1 + text.length
    const after = strippedSource[closeIndex + 1]
    if (after === undefined || !/[/A-Za-z]/.test(after)) continue

    spans.push({ start: openIndex + 1, text })
  }
  return spans
}

/** Replace every balanced `{...}` group in `text` with spaces of the same
 * length, innermost first, so offsets into `text` are unchanged. */
function blankBraces(text) {
  let out = text
  let previous
  do {
    previous = out
    out = out.replace(/\{[^{}]*\}/g, (match) => " ".repeat(match.length))
  } while (out !== previous)
  return out
}

/** Does `span` contain a `!` that reads as sentence punctuation? See the
 * per-condition breakdown on `findExclamationMarks` below; shared by its
 * per-line pass (over `proseSpans`) and its whole-file pass (over
 * `jsxTextSpans`) so both apply exactly the same rule. */
function hasProseBang(span) {
  for (let i = 0; i < span.length; i += 1) {
    if (span[i] !== "!") continue
    const next = span[i + 1]
    if (next === undefined || /\s/.test(next)) return true
  }
  return false
}

/**
 * Absolute offsets, within `span` starting at `spanStart`, of every `!` in
 * `span` that reads as sentence punctuation by the same rule as
 * `hasProseBang`. Used for `jsxTextSpans` results, where a span can hold
 * more than one line and each qualifying `!` needs its own real line number
 * (whitespace after `!` includes `\n`, so a `!` at the end of a wrapped line
 * still counts, exactly as it should).
 */
function proseBangOffsets(span, spanStart) {
  const offsets = []
  for (let i = 0; i < span.length; i += 1) {
    if (span[i] !== "!") continue
    const next = span[i + 1]
    if (next === undefined || /\s/.test(next)) offsets.push(spanStart + i)
  }
  return offsets
}

/**
 * Every exclamation mark that reads as prose punctuation in one file's
 * source, as `{line, text}`. Same shape and the same reasoning as
 * `findEmDashes`: exported and pure so the classifier is unit-tested rather
 * than trusted, one finding per line.
 *
 * A `!` counts only when both of these hold:
 *   1. it sits inside a prose span — a string literal's contents
 *      (`proseSpans`, minus attribute-value and shell-command-shaped
 *      strings) or a JSX text node (`proseSpans` for a single-line one,
 *      `jsxTextSpans` for one prettier has wrapped across several lines) —
 *      never bare code, so `!isValid`, `!==`, `!!x` and a TypeScript
 *      non-null `x!` are never even examined.
 *   2. the character right after it, within that same span, is the end of
 *      the span (i.e. the original string's closing quote or the `<` that
 *      ended the JSX text node) or whitespace — the shape sentence
 *      punctuation actually has. `!==` inside a string, `!important` in a
 *      CSS-in-JS literal, and `!!x` written out in prose about code all fail
 *      this: the character after their `!` is `=` or a letter, never one a
 *      real "Wait!" or "Reconnected!" is followed by.
 *
 * Two passes over the same comment-stripped source, merged into one set of
 * line numbers (so a JSX text node caught by both the per-line and the
 * whole-file pass reports once, not twice):
 *
 *   - per line, via `proseSpans` — string literals, and a JSX text node that
 *     sits entirely on one line;
 *   - over the whole file, via `jsxTextSpans` — a JSX text node prettier has
 *     wrapped onto its own line(s), which never has a `>` or `<` on the same
 *     line as the text itself and so is invisible to the first pass.
 */
export function findExclamationMarks(source) {
  const stripped = stripComments(source)
  const lines = stripped.split("\n")
  const flaggedLines = new Set()

  lines.forEach((line, lineIndex) => {
    if (proseSpans(line).some(hasProseBang)) flaggedLines.add(lineIndex + 1)
  })

  const lineStarts = lineStartOffsets(stripped)
  for (const { start, text } of jsxTextSpans(stripped)) {
    for (const offset of proseBangOffsets(text, start)) {
      flaggedLines.add(lineForOffset(lineStarts, offset))
    }
  }

  return [...flaggedLines]
    .sort((a, b) => a - b)
    .map((lineNum) => ({ line: lineNum, text: lines[lineNum - 1].trim().slice(0, 120) }))
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
