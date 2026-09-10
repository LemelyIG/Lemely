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
 * Blanks `//`/`/* *\/` comments and every string/template literal,
 * preserving character offsets and newlines, so a brace or a keyword
 * appearing only inside a comment or a string cannot be mistaken for real
 * code — the same shape as `tests/unit/support/jsxSource.ts`'s
 * `stripComments`, duplicated locally (not imported) because this script
 * runs as plain Node ESM with no TypeScript loader, and that helper lives
 * in a `.ts` file.
 */
function stripCommentsAndStrings(source) {
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
        out += " "
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
      out += "  "
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
    out += c === "\n" ? "\n" : " "
    i += 1
  }
  return out
}

/**
 * True if no `skipWaiting(...)` call — bare or `self.`-qualified, since
 * `workbox-core` exports a `skipWaiting` helper importable either way —
 * appears at brace depth 0 (module scope) in `swSource`. A call nested
 * inside any block (most plausibly a `message` event listener) is gated by
 * construction: it cannot run until whatever wraps it does. A call at
 * depth 0 runs unconditionally the moment the worker script itself executes
 * — install time, before any client has agreed to anything — which is
 * exactly the regression this guards.
 *
 * Comment/string-aware (`stripCommentsAndStrings`) and depth-only, rather
 * than the earlier hand-rolled "find the nearest `addEventListener` and
 * brace-match its callback" matcher: that approach false-failed on a
 * destructured handler param (`({ data }) =>`, whose own balanced braces
 * confused the "find the first `{` after the match" step) and false-passed
 * on a commented-out listener contributing a stray, uncounted brace. Pure
 * depth-0 detection has neither failure mode and degrades safely — a call
 * this can't prove is gated is reported as a failure, never silently
 * accepted.
 */
function isSkipWaitingGated(swSource) {
  const cleaned = stripCommentsAndStrings(swSource)
  const callPattern = /(?:self\.)?skipWaiting\s*\(/g
  const callStarts = new Set([...cleaned.matchAll(callPattern)].map((m) => m.index))
  if (callStarts.size === 0) return true

  let depth = 0
  for (let i = 0; i < cleaned.length; i++) {
    if (callStarts.has(i) && depth === 0) return false
    const c = cleaned[i]
    if (c === "{") depth++
    else if (c === "}") depth--
  }
  return true
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

/** Every `components/ui/*.tsx` element with both `onClick` and `hover:` on
 * its own opening tag must also carry `active:` on that same tag — the
 * 8-state component contract (DESIGN.md §12) applied mechanically to the
 * one state most likely to be forgotten. Scoped per element
 * (`classNameScopedTags`), not file-wide substring matching: a file with
 * two `hover:`+`onClick` elements where only one also has `active:` must
 * still fail on the other, which a bare `source.includes("active:")` check
 * cannot see. */
function checkHoverRequiresActive(files) {
  const offenders = new Set()
  for (const [relPath, source] of Object.entries(files)) {
    if (!relPath.startsWith("components/ui/")) continue
    for (const tag of classNameScopedTags(source)) {
      if (!tag.includes("onClick")) continue
      if (!tag.includes("hover:")) continue
      if (!tag.includes("active:")) offenders.add(relPath)
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
    name: "components/ui/*.tsx: every onClick + hover: element also has active:",
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
    name: "sw.ts: skipWaiting() never runs at module scope (depth 0)",
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
