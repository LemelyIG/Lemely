/*
 * The shared source lexer the tree-walking gates read `.tsx` through (P7.1).
 *
 * ── Why this file exists ───────────────────────────────────────────────────
 *
 * Six gates walk `src/**` and scan source text: `a11yRules`, `contrastRules`,
 * `elevationScale`, `adaptRules`, `motionDefaults` and `utilityExistence`.
 * Every one of them carried its own `stripComments`, in four distinct versions
 * — two byte-identical, one identical apart from two comments, one a
 * three-line regex, one line-based. They exist because each gate's author hit
 * the same problem (a rule must not fire on a class name quoted in prose) and
 * solved it again.
 *
 * ── The defect that made consolidating them urgent ─────────────────────────
 *
 * The string-aware version treats `'` as opening a JavaScript string wherever
 * it appears. In a `.tsx` file, an apostrophe also appears in **JSX text**, and
 * this product's own error-copy idiom is "Couldn't load your classes" — so the
 * lexer opened a string it never should have and stayed in it until the next
 * stray apostrophe, anywhere below. Between those two points comments were not
 * blanked and the gate read prose as code.
 *
 * Measured before fixing, not assumed: **25 of 125 `.tsx` files** desynchronise
 * this way, several ending the file still inside a phantom string. The 6.4
 * accessibility sweep, which "found nothing", read all of them through it.
 *
 * `a11yRules.test.ts`'s own header warns about precisely this failure and
 * believed it had been fixed. It had been fixed for apostrophes **inside
 * comments** — blanking comments removes those. The apostrophe in `Couldn't` is
 * not in a comment. That is the harmful direction of the bug the header
 * describes: a false positive announces itself, a swallowed region is a gate
 * quietly reading less of the product than its name claims.
 *
 * ── The rule that fixes it ─────────────────────────────────────────────────
 *
 * A quote opens a string only where a string could legally begin. In JS/TS an
 * identifier character can never be immediately followed by a string opener —
 * `Couldn` `'` `t` is not expressible as code — so a quote whose previous
 * character is a letter, digit, `_`, `$`, or a closing bracket is text, not a
 * delimiter. Closing is unchanged: once the lexer is genuinely inside a string,
 * the matching quote ends it wherever it sits.
 *
 * This is deliberately not a JSX parser. It does not need to be: the gates ask
 * "is this character inside a comment", and the only thing that made them wrong
 * was a class of quote that cannot be a delimiter in the first place.
 */

import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"

/** True where `c` cannot be immediately followed by a string opener in JS/TS. */
function closesAnExpression(c: string | undefined): boolean {
  return c !== undefined && /[A-Za-z0-9_$)\]}]/.test(c)
}

/**
 * Blanks comments, preserving every offset and line number, so a rule that
 * scans for code cannot fire on prose.
 *
 * Run every source scan through this. Never scan raw source: a class name or a
 * tag quoted in a comment is indistinguishable from the real thing otherwise,
 * which is how `elevationScale` first reported the best comment in the file.
 */
export function stripComments(source: string): string {
  let out = ""
  let i = 0
  type State = "code" | "line" | "block" | "single" | "double" | "template"
  let state: State = "code"
  /* Brace depth inside each open `${…}`. A template interpolation holds real
   * code — `DeviceLimitNotice.tsx` puts a three-line comment inside one — and a
   * lexer that stays in "template" until the closing backtick reads all of it
   * as string content. Empty means we are not inside an interpolation. */
  const interpolation: number[] = []

  while (i < source.length) {
    const c = source[i]
    const n = source[i + 1]

    if (state === "code") {
      if (interpolation.length > 0) {
        if (c === "{") {
          interpolation[interpolation.length - 1] += 1
        } else if (c === "}") {
          if (interpolation[interpolation.length - 1] === 0) {
            interpolation.pop()
            state = "template"
            out += c
            i += 1
            continue
          }
          interpolation[interpolation.length - 1] -= 1
        }
      }
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
      // The P7.1 rule. `previous` is the raw preceding character; a quote that
      // follows an identifier or a closing bracket is JSX text ("Couldn't",
      // "axe's", "{n} papers' worth") and opens nothing.
      if (c === "'" || c === '"' || c === "`") {
        if (!closesAnExpression(source[i - 1])) {
          state = c === "'" ? "single" : c === '"' ? "double" : "template"
        }
      }
      out += c
      i += 1
      continue
    }

    if (state === "line") {
      if (c === "\n") {
        state = "code"
        out += c
      } else {
        out += " "
      }
      i += 1
      continue
    }

    if (state === "block") {
      if (c === "*" && n === "/") {
        state = "code"
        out += "  "
        i += 2
        continue
      }
      // Newlines are kept so reported line numbers stay true to the file.
      out += c === "\n" ? "\n" : " "
      i += 1
      continue
    }

    // Inside a string literal.
    if (c === "\\") {
      out += c + (source[i + 1] ?? "")
      i += 2
      continue
    }
    if (state === "template" && c === "$" && n === "{") {
      interpolation.push(0)
      state = "code"
      out += "${"
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
    out += c
    i += 1
  }

  return out
}

/** Every `.tsx` under `dir`, recursively. */
export function sourceFiles(dir: string, extension = ".tsx"): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path, extension))
      continue
    }
    if (entry.endsWith(extension)) out.push(path)
  }
  return out
}

/** Repo-relative, forward-slashed, so a finding reads the same on any host. */
export function relativeTo(root: string, absolute: string): string {
  return pathRelative(root, absolute).split("\\").join("/")
}

/** Read and comment-strip every `.tsx` under `dir`. */
export function parsedSources(dir: string): { file: string; source: string }[] {
  return sourceFiles(dir).map((file) => ({
    file,
    source: stripComments(readFileSync(file, "utf8")),
  }))
}
