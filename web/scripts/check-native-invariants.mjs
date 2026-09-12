#!/usr/bin/env node
/*
 * Native-mechanics regression guard (packet A8).
 *
 * `tests/unit/nativeMechanics.test.ts` (P/A1) already pins most of these as
 * vitest assertions against the real tree — this script exists because a
 * vitest run isn't a mechanical CI/lint gate on its own here (`npm run
 * lint` never runs the unit suite), and the audit dossier's several
 * `x-*`/mechanics findings want a standalone, scriptable check that fails
 * fast and prints a clear pass/fail per assertion. Wired into `npm run
 * lint` (`package.json`) so a regression on any of these surfaces on every
 * PR, not only when someone happens to run the unit suite. Also wired into
 * CI's `web` job's own unit-test step directly (`npm test`), which is the
 * thing that actually runs `nativeMechanics.test.ts` itself — this script
 * is a second, independent encoding of the same rules, not a replacement
 * for running that suite (A8 review fix: CI previously ran neither).
 *
 * `runChecks` is the whole decision surface, structured to be importable
 * and testable against fixture strings — see `tests/unit/
 * checkNativeInvariants.test.ts`, one deliberately-failing fixture per
 * assertion. Everything below `main()` is a thin CLI wrapper: read the real
 * files, call `runChecks`, print pass/fail per check, exit 1 on any
 * failure.
 *
 * The two `--phase-b` checks are Phase B invariants that do not hold yet in
 * Phase A by design (`RouteFallback` is still the real route-chunk fallback
 * until B1 replaces it with a pre-mount shell continuation; a modal's
 * `document.body.style.overflow = "hidden"` scroll lock is still in use
 * until B2 replaces it with the FullscreenDrawer's own mechanism) — checked
 * only when the flag is passed, never enforced by plain `npm run
 * check:native`/`npm run lint`. Confirmed empirically (A8 review fix):
 * `--phase-b` genuinely fails both right now against the real tree
 * (routes.tsx still has multiple `fallback={<RouteFallback` occurrences;
 * `document.body.style.overflow = "hidden"` is still set in at least one
 * modal/drawer component) — the gating mechanism itself was always
 * correct, only an earlier commit message's claim that both were "already
 * true today" was wrong.
 */

import { readFileSync, readdirSync, statSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, "..")
const SRC = path.join(ROOT, "src")

/** The matching `}` for the `{` at `source[openIndex]`, or -1 if unbalanced. */
function findMatchingBrace(source, openIndex) {
  let depth = 0
  for (let i = openIndex; i < source.length; i++) {
    if (source[i] === "{") depth++
    else if (source[i] === "}") {
      depth--
      if (depth === 0) return i
    }
  }
  return -1
}

/** The content of the first brace-balanced block whose opening `{` follows
 * `startPattern`'s match — nested braces respected, so (unlike a `[\s\S]*?\}`
 * non-greedy regex) this cannot stop at an inner rule's own closing brace,
 * and (unlike `[\s\S]*` to end-of-file) cannot spill past the block's own
 * true close into unrelated later CSS. Returns `null` if not found. */
function extractBalancedBlock(source, startPattern) {
  const match = source.match(startPattern)
  if (!match) return null
  const braceStart = source.indexOf("{", match.index)
  if (braceStart === -1) return null
  const braceEnd = findMatchingBrace(source, braceStart)
  if (braceEnd === -1) return null
  return source.slice(braceStart + 1, braceEnd)
}

/**
 * Blanks `//`/`/* *\/` comments, preserving character offsets, newlines, and
 * — unlike `stripCommentsAndStrings` below — every string/template literal's
 * real content, so a quoted event name like `"message"` stays visible for
 * pattern matching. String-*aware* rather than string-blanking: `//`/`/&#42;`
 * appearing inside a string (a URL, say) is correctly left alone rather than
 * mistaken for a real comment start, but the string's own characters pass
 * through unchanged. Same length and character offsets as
 * `stripCommentsAndStrings`'s output for the same input, which is what lets
 * `isSkipWaitingGated` locate a pattern in this function's output and then
 * brace-match from that same index in the other's.
 *
 * Neither this nor `stripCommentsAndStrings` tracks regex-literal state —
 * a `/pattern/` containing an unescaped quote or brace can desynchronise
 * both lexers' state machines. Out of proportion to fix properly (a real
 * regex/string disambiguator needs to know whether the preceding token
 * could start an expression, i.e. needs an actual parser) for a CI guard
 * over one small, human-reviewed file — `sw.ts`'s one regex today
 * (`/^\/api/`) is quote/brace-free and does not trigger this. Noted here
 * rather than fixed so nobody mistakes this for airtight.
 */
function stripComments(source, { blankStrings }) {
  let out = ""
  let i = 0
  let state = "code"
  while (i < source.length) {
    const c = source[i]
    const n = source[i + 1]
    if (state === "code") {
      if (c === "/" && n === "/") {
        state = "line"
        out += "  "
        i += 2
        continue
      }
      if (c === "/" && n === "*") {
        state = "block"
        out += "  "
        i += 2
        continue
      }
      if (c === "'" || c === '"' || c === "`") {
        state = c === "'" ? "single" : c === '"' ? "double" : "template"
        out += blankStrings ? " " : c
        i += 1
        continue
      }
      out += c
      i += 1
      continue
    }
    if (state === "line") {
      out += c === "\n" ? c : " "
      i += 1
      if (c === "\n") state = "code"
      continue
    }
    if (state === "block") {
      if (c === "*" && n === "/") {
        state = "code"
        out += "  "
        i += 2
        continue
      }
      out += c === "\n" ? "\n" : " "
      i += 1
      continue
    }
    // single | double | template — inside a string/template literal.
    if (c === "\\") {
      out += blankStrings ? "  " : source.slice(i, i + 2)
      i += 2
      continue
    }
    if (
      (state === "single" && c === "'") ||
      (state === "double" && c === '"') ||
      (state === "template" && c === "`")
    ) {
      state = "code"
    }
    out += blankStrings ? (c === "\n" ? "\n" : " ") : c
    i += 1
  }
  return out
}

const stripCommentsAndStrings = (source) => stripComments(source, { blankStrings: true })
const stripCommentsOnly = (source) => stripComments(source, { blankStrings: false })

/**
 * True if every `skipWaiting(...)` call — bare or `self.`-qualified, since
 * `workbox-core` exports a `skipWaiting` helper importable either way —
 * sits specifically inside a `self.addEventListener("message", ...)`
 * callback body. Such a call is gated on the client explicitly asking to
 * skip waiting; anything else — module scope, or nested in some other block
 * that still runs unconditionally at install time
 * (`if (import.meta.env.PROD) { self.skipWaiting() }`,
 * `try { self.skipWaiting() } catch {}`) — is exactly the regression this
 * guards, and previously slipped through a looser "nested inside *any*
 * block counts as gated" version of this check (A8 review fix): being
 * nested proves nothing about *when* the block runs.
 *
 * Two comment/string-aware lexer passes locate this precisely:
 * `stripCommentsOnly` finds the real `addEventListener("message", ...)`
 * call sites (string content has to stay visible to match the quoted event
 * name), and `stripCommentsAndStrings` — character-offset-aligned with the
 * first pass — brace-matches each one's callback body so a brace inside an
 * unrelated string or comment can't corrupt the range. A call is gated only
 * if its position falls inside one of those specific ranges — not merely
 * "inside some brace, somewhere."
 *
 * This replaces an even earlier hand-rolled matcher that anchored to
 * `addEventListener` too, but found a callback's body via a bare
 * `indexOf("{", match.index)` — which matched a destructured handler
 * param's own `{` (`({ data }) =>`) before the real block, false-failing.
 * The fix here anchors to the arrow (`=>`) first, then requires a `{`
 * immediately after it (only whitespace between): a parameter list's own
 * braces sit *before* the arrow, so they're never candidates, regardless of
 * what the parameter list contains. An arrow with an implicit-return
 * expression (no `{` right after `=>`) has no block to bound and is
 * treated as ungated — fails safe, the same choice as an unrecognised
 * `skipWaiting` call anywhere else. The arrow search is bounded to a short
 * window after the `addEventListener` match (a parameter list is never
 * remotely that long) so a call passing a *named* handler reference
 * instead of an inline arrow — `addEventListener("message", handler)`,
 * not currently used anywhere in this codebase — cannot accidentally latch
 * onto some unrelated arrow much later in the file.
 */
function isSkipWaitingGated(swSource) {
  const forPatterns = stripCommentsOnly(swSource)
  const forBraces = stripCommentsAndStrings(swSource)

  const callPattern = /(?:self\.)?skipWaiting\s*\(/g
  const callStarts = [...forBraces.matchAll(callPattern)].map((m) => m.index)
  if (callStarts.length === 0) return true

  const ARROW_SEARCH_WINDOW = 200
  const gatedRanges = []
  const listenerPattern = /addEventListener\(\s*["']message["']/g
  let match
  while ((match = listenerPattern.exec(forPatterns))) {
    const windowEnd = match.index + ARROW_SEARCH_WINDOW
    const arrowIndex = forPatterns.indexOf("=>", match.index)
    if (arrowIndex === -1 || arrowIndex > windowEnd) continue
    let cursor = arrowIndex + 2
    while (/\s/.test(forPatterns[cursor] ?? "")) cursor++
    if (forPatterns[cursor] !== "{") continue
    const braceStart = cursor
    const braceEnd = findMatchingBrace(forBraces, braceStart)
    if (braceEnd === -1) continue
    gatedRanges.push([braceStart, braceEnd])
  }

  return callStarts.every((start) => gatedRanges.some(([s, e]) => start > s && start < e))
}

/** `min-h-screen` in a class list, outside an `<aside>` sidebar (desktop-only,
 * deliberately still `min-h-screen`) and outside a comment/prose line that
 * merely quotes the class name. There is no "pairs correctly with
 * min-h-dvh" exemption: Tailwind v4 emits `.min-h-screen` after
 * `.min-h-dvh` in its own sorted utility output regardless of source order,
 * and both are single-class selectors at equal specificity with neither
 * behind `@media`/`@supports` — later-in-cascade wins at equal specificity,
 * so `min-h-screen` always overrides `min-h-dvh` when both are present,
 * silently. The class must be *absent*, not merely paired; see
 * `tests/unit/nativeMechanics.test.ts`'s own "min-h-dvh alone, no
 * min-h-screen fallback" describe block, which this ports. */
function checkMinHScreen(files) {
  const offenders = []
  for (const [relPath, source] of Object.entries(files)) {
    source.split("\n").forEach((line, i) => {
      if (!line.includes("min-h-screen")) return
      if (line.includes("<aside")) return
      const trimmed = line.trim()
      if (trimmed.startsWith("*") || trimmed.startsWith("//")) return
      offenders.push(`${relPath}:${i + 1}`)
    })
  }
  return offenders
}

/** Every JSX opening tag in `source` carrying a `className=` attribute, as
 * its full `<Tag ...>` text — brace/paren-depth aware while scanning for
 * the tag's own closing `>`, so an expression inside `className={cn(...)}`
 * (which may itself contain `>`, `{`, or `}`) cannot end the tag early. */
function classNameScopedTags(source) {
  const tags = []
  const pattern = /className=/g
  let match
  while ((match = pattern.exec(source))) {
    const openIndex = source.lastIndexOf("<", match.index)
    if (openIndex === -1) continue
    let depth = 0
    let tagEnd = -1
    for (let i = match.index; i < source.length; i++) {
      const c = source[i]
      if (c === "{" || c === "(") depth++
      else if (c === "}" || c === ")") depth--
      else if (c === ">" && depth <= 0) {
        tagEnd = i
        break
      }
    }
    if (tagEnd === -1) continue
    tags.push(source.slice(openIndex, tagEnd + 1))
  }
  return tags
}

/** Every balanced-paren `cva(...)` call's full argument list in `source` —
 * base classes array, the variants object, all of it — as one string per
 * call. `class-variance-authority` recipes (e.g. `button.tsx`'s `button =
 * cva([...], { variants: {...} })`) hold their `hover:`/`active:` classes as
 * plain string literals inside that structure, not on a JSX tag at all;
 * `classNameScopedTags` above cannot see them. */
function cvaScopedBlocks(source) {
  const blocks = []
  const pattern = /\bcva\(/g
  let match
  while ((match = pattern.exec(source))) {
    const parenStart = match.index + match[0].length - 1
    let depth = 0
    let parenEnd = -1
    for (let i = parenStart; i < source.length; i++) {
      const c = source[i]
      if (c === "(") depth++
      else if (c === ")") {
        depth--
        if (depth === 0) {
          parenEnd = i
          break
        }
      }
    }
    if (parenEnd === -1) continue
    blocks.push(source.slice(parenStart, parenEnd + 1))
  }
  return blocks
}

/**
 * Every interactive `components/ui/*.tsx` control must pair `hover:` with
 * `active:` — the 8-state component contract (DESIGN.md §12) applied
 * mechanically to the one state most likely to be forgotten. Two
 * complementary scopes, since this codebase styles interactive elements two
 * different ways:
 *
 * - **Inline on the JSX tag** (`classNameScopedTags`): an element with both
 *   `onClick` and `hover:` on its own opening tag must also carry `active:`
 *   there. Scoped per element, not file-wide substring matching — a file
 *   with two such elements where only one also has `active:` still fails on
 *   the other, which a bare `source.includes("active:")` check cannot see.
 * - **A `cva(...)` variant recipe** (`cvaScopedBlocks`, A8 follow-up):
 *   `button.tsx` — this product's primary interactive control — declares no
 *   `onClick` of its own (it's a reusable primitive; callers pass one via
 *   props spreading) and keeps `hover:`/`active:` inside a `cva(...)` call's
 *   base array and variant strings rather than on a literal JSX tag, so the
 *   first scope alone never even looks at it. A `cva(...)` call with
 *   `hover:` anywhere in its argument list must also have `active:`
 *   somewhere in that same call — not necessarily the same variant string,
 *   since a recipe's base array applies to every variant.
 */
function checkHoverRequiresActive(files) {
  const offenders = new Set()
  for (const [relPath, source] of Object.entries(files)) {
    if (!relPath.startsWith("components/ui/")) continue
    for (const tag of classNameScopedTags(source)) {
      if (!tag.includes("onClick")) continue
      if (!tag.includes("hover:")) continue
      if (!tag.includes("active:")) offenders.add(relPath)
    }
    for (const block of cvaScopedBlocks(source)) {
      if (!block.includes("hover:")) continue
      if (!block.includes("active:")) offenders.add(relPath)
    }
  }
  return [...offenders]
}

function checkNoBodyOverflowHidden(files) {
  const offenders = []
  for (const [relPath, source] of Object.entries(files)) {
    if (source.includes('document.body.style.overflow = "hidden"')) offenders.push(relPath)
  }
  return offenders
}

/** `.lm-app-header`'s inset must be additive (a `padding-top` that reads a
 * `--lm-app-header-pt` custom property with a `0px` fallback, then a second,
 * standalone-only rule that adds the safe-area inset to it) rather than a
 * bare fixed value that would zero out a header's own existing padding —
 * see `index.css`'s own comment on this pair for the full reasoning. */
function checkLmAppHeaderAdditive(indexCss) {
  const blocks = [...indexCss.matchAll(/\.lm-app-header\s*\{([\s\S]*?)\}/g)].map((m) => m[1])
  if (blocks.length !== 2) return false
  if (!blocks[0].includes("padding-top: var(--lm-app-header-pt, 0px)")) return false
  return blocks[1].includes(
    "padding-top: calc(var(--lm-app-header-pt, 0px) + env(safe-area-inset-top))",
  )
}

/** The named `.lm-app-header-pt-4`/`.lm-app-header-pt-2\.5` utilities, off
 * the `--spacing` scale rather than an arbitrary Tailwind value (§14 rule 3). */
function checkLmAppHeaderPtUtilities(indexCss) {
  return (
    indexCss.includes(".lm-app-header-pt-4 {") &&
    indexCss.includes("--lm-app-header-pt: calc(var(--spacing) * 4)") &&
    indexCss.includes(".lm-app-header-pt-2\\.5 {") &&
    indexCss.includes("--lm-app-header-pt: calc(var(--spacing) * 2.5)")
  )
}

/** Every top-level nav/header surface applies `lm-nav-chrome`
 * (`-webkit-touch-callout: none; user-select: none`), and the nav drawer
 * applies it twice — to both the dialog panel and its trigger. */
const CHROME_FILES = [
  "components/ui/nav-drawer.tsx",
  "components/ui/nav-shells.tsx",
  "portals/student/index.tsx",
  "portals/teacher/index.tsx",
  "portals/admin/index.tsx",
  "portals/marketing/index.tsx",
]

function checkLmNavChrome(files) {
  const offenders = []
  for (const relPath of CHROME_FILES) {
    const source = files[relPath]
    if (!source || !source.includes("lm-nav-chrome")) offenders.push(relPath)
  }
  const navDrawer = files["components/ui/nav-drawer.tsx"]
  if (navDrawer) {
    const count = (navDrawer.match(/lm-nav-chrome/g) ?? []).length
    if (count !== 2) offenders.push("components/ui/nav-drawer.tsx (expected lm-nav-chrome twice)")
  }
  return offenders
}

/**
 * The whole check suite, run against in-memory fixtures.
 *
 * @param {object} input
 * @param {string} input.indexHtml
 * @param {string} input.indexCss
 * @param {string} input.inputTsx
 * @param {string} input.textareaTsx
 * @param {string} input.swSource
 * @param {Record<string, string>} input.files - every `web/src/**\/*.{ts,tsx}`
 *   file, keyed by its path relative to `web/src/`.
 * @param {boolean} [input.phaseB] - also run the two Phase B checks.
 */
export function runChecks({ indexHtml, indexCss, inputTsx, textareaTsx, swSource, files, phaseB = false }) {
  const allFiles = files ?? {}
  const checks = []

  checks.push({
    name: "index.html viewport meta: viewport-fit=cover, interactive-widget=resizes-content",
    pass: indexHtml.includes("viewport-fit=cover") && indexHtml.includes("interactive-widget=resizes-content"),
  })

  const htmlBodyMatch = indexCss.match(/html,\s*body\s*\{([\s\S]*?)\}/)
  const htmlBodyBlock = htmlBodyMatch ? htmlBodyMatch[1] : ""
  checks.push({
    name: "index.css html, body rule: overflow-x: clip",
    pass: htmlBodyBlock.includes("overflow-x: clip"),
  })
  checks.push({
    name: "index.css html, body rule: -webkit-tap-highlight-color: transparent",
    pass: htmlBodyBlock.includes("-webkit-tap-highlight-color: transparent"),
  })
  checks.push({
    name: "index.css html, body rule: overscroll-behavior-y: contain",
    pass: htmlBodyBlock.includes("overscroll-behavior-y: contain"),
  })

  const pointerCoarseBlock = extractBalancedBlock(indexCss, /@media \(pointer: coarse\)\s*/)
  checks.push({
    name: "index.css @media (pointer: coarse): touch-action: manipulation",
    pass: pointerCoarseBlock ? pointerCoarseBlock.includes("touch-action: manipulation") : false,
  })

  const lmScrollMatch = indexCss.match(/\.lm-scroll\s*\{([\s\S]*?)\}/)
  checks.push({
    name: "index.css .lm-scroll: overscroll-behavior: contain",
    pass: lmScrollMatch ? lmScrollMatch[1].includes("overscroll-behavior: contain") : false,
  })

  checks.push({
    name: "index.css --fs-field token is 16px",
    pass: indexCss.includes("--fs-field: 16px"),
  })

  checks.push({
    name: "index.css has at least one env(safe-area-inset-*)",
    pass: /env\(safe-area-inset-/.test(indexCss),
  })

  checks.push({
    name: "index.css has at least one @media (display-mode: standalone)",
    pass: indexCss.includes("@media (display-mode: standalone)"),
  })

  checks.push({
    name: "index.css .lm-app-header inset is additive (base + standalone rules)",
    pass: checkLmAppHeaderAdditive(indexCss),
  })

  checks.push({
    name: "index.css .lm-app-header-pt-4 / .lm-app-header-pt-2\\.5 named utilities exist",
    pass: checkLmAppHeaderPtUtilities(indexCss),
  })

  checks.push({
    name: "components/ui/input.tsx: uses text-field, not text-body-md, on the native element",
    pass: inputTsx.includes("text-field") && !inputTsx.includes("text-body-md"),
  })

  checks.push({
    name: "components/ui/textarea.tsx: uses text-field, not text-body-md, on the native element",
    pass: textareaTsx.includes("text-field") && !textareaTsx.includes("text-body-md"),
  })

  const minHScreenOffenders = checkMinHScreen(allFiles)
  checks.push({
    name: "no class-list min-h-screen outside an <aside> sidebar",
    pass: minHScreenOffenders.length === 0,
    detail: minHScreenOffenders.join(", "),
  })

  const hoverActiveOffenders = checkHoverRequiresActive(allFiles)
  checks.push({
    name: "components/ui/*.tsx: every hover: (inline tag or cva recipe) also has active:",
    pass: hoverActiveOffenders.length === 0,
    detail: hoverActiveOffenders.join(", "),
  })

  const navChromeOffenders = checkLmNavChrome(allFiles)
  checks.push({
    name: "every top-level nav/header applies lm-nav-chrome (nav-drawer.tsx twice)",
    pass: navChromeOffenders.length === 0,
    detail: navChromeOffenders.join(", "),
  })

  checks.push({
    name: 'index.html: apple-mobile-web-app-status-bar-style="default"',
    pass: indexHtml.includes('<meta name="apple-mobile-web-app-status-bar-style" content="default" />'),
  })

  checks.push({
    name: 'sw.ts: skipWaiting() only runs inside addEventListener("message", ...)',
    pass: isSkipWaitingGated(swSource ?? ""),
  })

  if (phaseB) {
    const routeFallbackCount = ((allFiles["routes.tsx"] ?? "").match(/fallback=\{<RouteFallback/g) ?? [])
      .length
    checks.push({
      name: "[phase-b] routes.tsx: zero fallback={<RouteFallback occurrences",
      pass: routeFallbackCount === 0,
      detail: String(routeFallbackCount),
    })

    const overflowOffenders = checkNoBodyOverflowHidden(allFiles)
    checks.push({
      name: '[phase-b] no document.body.style.overflow = "hidden" anywhere in web/src',
      pass: overflowOffenders.length === 0,
      detail: overflowOffenders.join(", "),
    })
  }

  return { checks, passed: checks.every((c) => c.pass) }
}

// ---------------------------------------------------------------------------
// CLI wrapper — reads the real tree, calls runChecks, prints and exits.
// ---------------------------------------------------------------------------

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (statSync(full).isDirectory()) yield* walk(full)
    else if (/\.tsx?$/.test(full)) yield full
  }
}

function readAllSourceFiles() {
  const files = {}
  for (const file of walk(SRC)) {
    files[path.relative(SRC, file).split(path.sep).join("/")] = readFileSync(file, "utf8")
  }
  return files
}

function main() {
  const phaseB = process.argv.includes("--phase-b")

  const indexHtml = readFileSync(path.join(ROOT, "index.html"), "utf8")
  const indexCss = readFileSync(path.join(SRC, "index.css"), "utf8")
  const files = readAllSourceFiles()
  const inputTsx = files["components/ui/input.tsx"]
  const textareaTsx = files["components/ui/textarea.tsx"]
  const swSource = files["sw.ts"]

  if (!inputTsx || !textareaTsx || !swSource) {
    console.error("check-native-invariants: expected files under web/src are missing.")
    process.exit(1)
  }

  const { checks, passed } = runChecks({
    indexHtml,
    indexCss,
    inputTsx,
    textareaTsx,
    swSource,
    files,
    phaseB,
  })

  for (const check of checks) {
    const mark = check.pass ? "PASS" : "FAIL"
    const detail = !check.pass && check.detail ? ` — ${check.detail}` : ""
    console.log(`[${mark}] ${check.name}${detail}`)
  }

  if (!passed) {
    console.error(`\ncheck-native-invariants: ${checks.filter((c) => !c.pass).length} check(s) failed.`)
    process.exit(1)
  }
  console.log(`\ncheck-native-invariants: all ${checks.length} check(s) passed.`)
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main()
}
