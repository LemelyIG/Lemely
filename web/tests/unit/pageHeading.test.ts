import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { PageHeading } from "@/components/ui/page-heading"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")

describe("PageHeading (D11)", () => {
  it("a repeating heading is visually hidden on the native frame only, and stays an h1", () => {
    const out = renderToStaticMarkup(createElement(PageHeading, { repeatsTitle: true, className: "text-display-md" }, "Classes"))
    expect(out).toMatch(/^<h1 data-page-heading="title" class="[^"]*\bnative:sr-only\b[^"]*">Classes<\/h1>$/)
    expect(out).toContain("text-display-md")
  })
  it("a heading that says something else stays visible everywhere", () => {
    const out = renderToStaticMarkup(createElement(PageHeading, { repeatsTitle: false }, "Hi, Mariam"))
    expect(out).toMatch(/^<h1 data-page-heading="own"/)
    expect(out).not.toContain("sr-only")
  })
})

describe("no screen bypasses PageHeading", () => {
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => {
      const p = join(dir, f)
      return statSync(p).isDirectory() ? walk(p) : p.endsWith(".tsx") ? [p] : []
    })
  it("student and teacher screens render no raw <h1> except an always-hidden one", () => {
    const offenders: string[] = []
    for (const file of [...walk(join(SRC, "portals/student")), ...walk(join(SRC, "portals/teacher"))]) {
      for (const [i, line] of readFileSync(file, "utf8").split("\n").entries()) {
        const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "")
        if (/^\s*\*/.test(line)) continue // block comment body
        if (/<h1\b/.test(code) && !/<h1 className="sr-only">/.test(code)) offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
