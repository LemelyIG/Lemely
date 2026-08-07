#!/usr/bin/env node
/*
 * Design-token regression guard (P3.10 chunk c).
 *
 * `web/` has no unit-test runner (see BUILD/STATE.md — standing one up is an
 * open P3.10 item), and these two invariants are exactly the kind that fail
 * *silently*: no type error, no lint error, no console error, no axe
 * violation. They degrade typography to whatever was inherited, which reads
 * as "slightly off" rather than "broken", so nothing in the existing gate
 * chain would ever report them. Hence a standalone script rather than
 * nothing until a runner exists.
 *
 * If a real runner lands later, these two checks should move into it
 * verbatim and this file should go.
 *
 * 1. Every custom `text-*` class we define must be classified by
 *    tailwind-merge as a FONT SIZE, not as a text COLOR.
 *
 *    twMerge's default config knows only its own font-size names plus
 *    t-shirt-shaped suffixes. Anything else beginning `text-` falls into the
 *    `text-color` class group, and then `cn("text-display-md", "text-t1")`
 *    resolves as two colors in conflict and drops one — silently losing
 *    either the type or the color. That bug was live in five shared C-*
 *    components before this chunk (trend-sparkline x2, boundary-bar,
 *    confidence-indicator, paper-identity), and the retrofit multiplied the
 *    at-risk call sites across the whole teacher portal, so it is now
 *    load-bearing. `lib/utils.ts` registers the names; this proves the
 *    registration actually took effect.
 *
 * 2. No arbitrary font-size / colour / radius literal may reappear in the
 *    retrofitted portals. The retrofit is only worth doing once.
 */
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { fileURLToPath } from "node:url"
import { extendTailwindMerge } from "tailwind-merge"

const SRC = fileURLToPath(new URL("../src/", import.meta.url))
const failures = []

// ── 1. tailwind-merge classification ──────────────────────────────────────
const utils = readFileSync(join(SRC, "lib/utils.ts"), "utf8")
const block = utils.match(/CUSTOM_FONT_SIZE_CLASSES = \[([\s\S]*?)\] as const/)
if (!block) {
  failures.push("lib/utils.ts: CUSTOM_FONT_SIZE_CLASSES not found — the twMerge font-size registration is gone")
} else {
  const names = [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
  const twMerge = extendTailwindMerge({
    extend: { classGroups: { "font-size": [{ text: names }] } },
  })
  // A type class and a colour must survive being merged together, in both
  // orders — that is the whole point of the registration.
  for (const name of names) {
    for (const [a, b] of [[`text-${name}`, "text-t1"], ["text-t1", `text-${name}`]]) {
      const merged = twMerge(`${a} ${b}`)
      if (!merged.includes(a) || !merged.includes(b)) {
        failures.push(`twMerge("${a} ${b}") => "${merged}" — one class was dropped; "text-${name}" is not registered as a font-size`)
      }
    }
  }
  // Two sizes must still collapse, or the registration has broken conflict
  // resolution instead of fixing classification.
  const both = twMerge("text-dense text-display-md")
  if (both !== "text-display-md") {
    failures.push(`twMerge("text-dense text-display-md") => "${both}" — expected the later font-size to win`)
  }
  // The list and the stylesheet must agree in BOTH directions. Forgetting to
  // register a newly added class is the dangerous direction (it reintroduces
  // the silent-drop bug); registering a name with no class behind it is just
  // dead config, but it means the two have drifted either way.
  const css = readFileSync(join(SRC, "index.css"), "utf8")
  const defined = new Set([
    ...[...css.matchAll(/^\.text-([a-z0-9-]+)\s*\{/gm)].map((m) => m[1]),
    ...[...css.matchAll(/^\s*--text-([a-z0-9-]+)\s*:/gm)].map((m) => m[1]),
  ])
  for (const name of names) {
    if (!defined.has(name)) {
      failures.push(`lib/utils.ts registers "text-${name}", but index.css defines no such class or theme key`)
    }
  }
  for (const name of defined) {
    if (!names.includes(name)) {
      failures.push(`index.css defines "text-${name}", but lib/utils.ts does not register it as a font-size — cn() will treat it as a text COLOR and silently drop it or the colour beside it`)
    }
  }
}

// ── 2. no arbitrary literals in the retrofitted portals ───────────────────
// `portals/student/` is deliberately absent: only its shell (index.tsx) was
// retrofitted in this chunk. Its screens still carry ~120 literals, which is
// recorded as measured debt in BUILD/STATE.md rather than silently claimed
// as clean here.
const RETROFITTED = ["portals/teacher", "portals/parent", "components", "portals/student/index.tsx"]
const BANNED = [
  [/\btext-\[[0-9.]+px\]/g, "arbitrary font size"],
  [/\brounded-\[[0-9.]+px\]/g, "arbitrary border radius"],
  [/oklch\(/g, "raw oklch colour"],
  [/#[0-9a-fA-F]{6}\b/g, "raw hex colour"],
]

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) yield* walk(full)
    else if (/\.tsx?$/.test(full)) yield full
  }
}

for (const target of RETROFITTED) {
  const full = join(SRC, target)
  const files = statSync(full).isDirectory() ? [...walk(full)] : [full]
  for (const file of files) {
    const text = readFileSync(file, "utf8")
    for (const [pattern, label] of BANNED) {
      for (const match of text.matchAll(pattern)) {
        const line = text.slice(0, match.index).split("\n").length
        failures.push(`${relative(SRC, file)}:${line}  ${label} "${match[0]}" — use a token from index.css`)
      }
    }
  }
}

if (failures.length) {
  console.error(`design-token check FAILED (${failures.length})`)
  for (const f of failures) console.error(`  ${f}`)
  process.exit(1)
}
console.log("design-token check OK")
