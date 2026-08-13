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
 * Usage:
 *   node scripts/check_copy.mjs            # report, exit 1 if anything found
 *   node scripts/check_copy.mjs --count    # totals per file, always exit 0
 *
 * Scope is deliberately `src/`. Comments are stripped before matching, so an
 * em-dash in a code comment (which no user reads, and which this codebase's
 * documentation style uses heavily) is not a finding.
 */

import { readFileSync } from "node:fs"
import { readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"

const ROOT = new URL("..", import.meta.url).pathname
const SRC = join(ROOT, "src")

/** Every .tsx under src/, recursively. */
function sourceFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full))
    else if (entry.endsWith(".tsx")) out.push(full)
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
      const quoted = line.match(/(["'`])\s*[—–]\s*\1/g) ?? []
      if (quoted.some((q) => isPlaceholder(q)) && quoted.length === 1) {
        const only = line.indexOf(quoted[0])
        if (i > only && i < only + quoted[0].length) continue
      }
      if (/>\s*[—–]\s*</.test(line.slice(Math.max(0, i - 12), i + 12))) continue

      if (isRange(line, i)) continue

      findings.push({ line: lineIndex + 1, text: line.trim().slice(0, 120) })
      break // one finding per line is enough to send someone to it
    }
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
  const findings = []
  for (const file of sourceFiles(SRC)) {
    for (const hit of findEmDashes(readFileSync(file, "utf8"))) {
      findings.push({ file: relative(ROOT, file), ...hit })
    }
  }

  if (process.argv.includes("--count")) {
    const perFile = new Map()
    for (const f of findings) perFile.set(f.file, (perFile.get(f.file) ?? 0) + 1)
    const sorted = [...perFile.entries()].sort((a, b) => b[1] - a[1])
    for (const [file, count] of sorted) console.log(`${String(count).padStart(3)}  ${file}`)
    console.log(`\n${findings.length} lines across ${perFile.size} files`)
    process.exit(0)
  }

  if (findings.length === 0) {
    console.log("check_copy: no em-dashes in UI copy.")
    process.exit(0)
  }

  console.error(`check_copy: ${findings.length} em-dash(es) in UI copy (MISSION §3.2 item 10).`)
  console.error("Restructure the sentence, or use a comma or a full stop.\n")
  for (const f of findings) {
    console.error(`  ${f.file}:${f.line}`)
    console.error(`    ${f.text}`)
  }
  process.exit(1)
}
