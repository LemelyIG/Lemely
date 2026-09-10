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
 * PR, not only when someone happens to run the unit suite.
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
 * check:native`/`npm run lint`.
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

/**
 * True if every `self.skipWaiting()` call in `swSource` sits textually
 * inside a `self.addEventListener("message", ...)` callback body — i.e. is
 * gated on the client explicitly asking to skip waiting, rather than
 * running unconditionally at module scope on every install.
 */
function isSkipWaitingGated(swSource) {
  const skipWaitingCalls = [...swSource.matchAll(/self\.skipWaiting\(\)/g)]
  if (skipWaitingCalls.length === 0) return true

  const messageListenerRanges = []
  const listenerPattern = /addEventListener\(\s*["']message["']/g
  let match
  while ((match = listenerPattern.exec(swSource))) {
    const braceStart = swSource.indexOf("{", match.index)
    if (braceStart === -1) continue
    const braceEnd = findMatchingBrace(swSource, braceStart)
    if (braceEnd === -1) continue
    messageListenerRanges.push([braceStart, braceEnd])
  }

  return skipWaitingCalls.every((call) =>
    messageListenerRanges.some(([start, end]) => call.index > start && call.index < end),
  )
}

/** `min-h-screen` in a class list with no `min-h-dvh` on the same line —
 * excluding an `<aside>` sidebar (desktop-only, deliberately still
 * `min-h-screen`) and comment/prose lines that merely quote the class name. */
function checkMinHScreen(files) {
  const offenders = []
  for (const [relPath, source] of Object.entries(files)) {
    source.split("\n").forEach((line, i) => {
      if (!line.includes("min-h-screen")) return
      if (line.includes("<aside")) return
      const trimmed = line.trim()
      if (trimmed.startsWith("*") || trimmed.startsWith("//")) return
      if (line.includes("min-h-dvh")) return
      offenders.push(`${relPath}:${i + 1}`)
    })
  }
  return offenders
}

/** Every `components/ui/*.tsx` file with both `onClick` and `hover:` must
 * also carry `active:` — the 8-state component contract (DESIGN.md §12)
 * applied mechanically to the one state most likely to be forgotten. */
function checkHoverRequiresActive(files) {
  const offenders = []
  for (const [relPath, source] of Object.entries(files)) {
    if (!relPath.startsWith("components/ui/")) continue
    if (!source.includes("onClick")) continue
    if (!source.includes("hover:")) continue
    if (!source.includes("active:")) offenders.push(relPath)
  }
  return offenders
}

function checkNoBodyOverflowHidden(files) {
  const offenders = []
  for (const [relPath, source] of Object.entries(files)) {
    if (source.includes('document.body.style.overflow = "hidden"')) offenders.push(relPath)
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
    name: "index.css html, body rule: -webkit-tap-highlight-color: transparent",
    pass: htmlBodyBlock.includes("-webkit-tap-highlight-color: transparent"),
  })
  checks.push({
    name: "index.css html, body rule: overscroll-behavior-y: contain",
    pass: htmlBodyBlock.includes("overscroll-behavior-y: contain"),
  })

  const pointerCoarseMatch = indexCss.match(/@media \(pointer: coarse\) \{([\s\S]*)/)
  checks.push({
    name: "index.css @media (pointer: coarse): touch-action: manipulation",
    pass: pointerCoarseMatch ? pointerCoarseMatch[1].includes("touch-action: manipulation") : false,
  })

  const lmScrollMatch = indexCss.match(/\.lm-scroll\s*\{([\s\S]*?)\}/)
  checks.push({
    name: "index.css .lm-scroll: overscroll-behavior: contain",
    pass: lmScrollMatch ? lmScrollMatch[1].includes("overscroll-behavior: contain") : false,
  })

  checks.push({
    name: "index.css --fs-field token is defined",
    pass: indexCss.includes("--fs-field"),
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
    name: "components/ui/input.tsx: no text-body-md on the native element",
    pass: !inputTsx.includes("text-body-md"),
  })

  checks.push({
    name: "components/ui/textarea.tsx: no text-body-md on the native element",
    pass: !textareaTsx.includes("text-body-md"),
  })

  const minHScreenOffenders = checkMinHScreen(allFiles)
  checks.push({
    name: "no min-h-screen without min-h-dvh on the same line",
    pass: minHScreenOffenders.length === 0,
    detail: minHScreenOffenders.join(", "),
  })

  const hoverActiveOffenders = checkHoverRequiresActive(allFiles)
  checks.push({
    name: "components/ui/*.tsx: onClick + hover: also has active:",
    pass: hoverActiveOffenders.length === 0,
    detail: hoverActiveOffenders.join(", "),
  })

  checks.push({
    name: "sw.ts: self.skipWaiting() is gated behind a message event listener",
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
