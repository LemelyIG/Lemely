#!/usr/bin/env node
// Renames retired Study Notebook utilities to the v5 Abyss M3 roles.
// Table: scripts/abyss-token-map.json. Run once with --compat, then any number
// of times without it (idempotent). --check exits 1 when a file would change.
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

export function rewriteClasses(source, map, { compat }) {
  const tokens = { ...map.tokens, ...(compat ? map.compat : {}) }
  const prefixes = [...map.prefixes].sort((a, b) => b.length - a.length).map(escape).join("|")
  const names = Object.keys(tokens).sort((a, b) => b.length - a.length).map(escape).join("|")
  // variants (hover:, md:, dark:...), prefix, token, optional /opacity, then a hard boundary
  const re = new RegExp(`(?<![\\w-])((?:[\\w-]+:)*)(${prefixes})-(${names})(\\/\\d+)?(?![\\w-])`, "g")
  return source.replace(re, (whole, variants, prefix, token, opacity = "") => {
    const pair = `${prefix}-${token}`
    const replaced = map.overrides[pair] ?? `${prefix}-${tokens[token]}`
    return `${variants}${replaced}${opacity}`
  })
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx|ts|css)$/.test(name) && name !== "index.css") out.push(p)
  }
  return out
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]
if (isMain) {
  const here = dirname(fileURLToPath(import.meta.url))
  const map = JSON.parse(readFileSync(join(here, "abyss-token-map.json"), "utf8"))
  const compat = process.argv.includes("--compat")
  const check = process.argv.includes("--check")
  let changed = 0
  for (const file of walk(join(here, "..", "src"))) {
    const before = readFileSync(file, "utf8")
    const after = rewriteClasses(before, map, { compat })
    if (after !== before) {
      changed++
      if (!check) writeFileSync(file, after)
      console.log(`${check ? "would change" : "changed"}: ${file}`)
    }
  }
  console.log(`${changed} file(s)`)
  if (check && changed) process.exit(1)
}
