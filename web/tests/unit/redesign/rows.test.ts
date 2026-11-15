import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { H2Row, HairRow, HairRows, RankRow, SubjectDot, subjectDotColor } from "@/components/redesign"

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, node))

describe("H2Row", () => {
  it("a heading with a trailing link", () => {
    const out = html(createElement(H2Row, { title: "Topics costing marks", link: { label: "All topics", to: "/parent/topics" } }))
    expect(out).toMatch(/<h2 class="rd-h2">Topics costing marks<\/h2>/)
    expect(out).toMatch(/<a class="rd-lnk"[^>]*href="\/parent\/topics"[^>]*>All topics<\/a>/)
  })
  it("a button link when there is no route, and a linked title", () => {
    const out = html(createElement(H2Row, { title: "Papers", titleTo: "/papers", link: { label: "More", onClick: () => {} } }))
    expect(out).toMatch(/<h2 class="rd-h2"><a class="rd-h2link"[^>]*href="\/papers"/)
    expect(out).toMatch(/<button type="button" class="rd-lnk">More<\/button>/)
  })
  it("a right slot replaces the link", () => {
    const out = html(createElement(H2Row, { title: "Your path to A*", link: { label: "x", to: "/x" }, right: createElement("div", { role: "tablist" }) }))
    expect(out).toContain('<div class="rd-h2row-right"><div role="tablist"></div></div>')
    expect(out).not.toContain("rd-lnk")
  })
})

describe("SubjectDot", () => {
  it("maps subjects by name or code to existing tokens, stable for unknowns", () => {
    expect(subjectDotColor("Mathematics")).toBe("var(--grade-a)")
    expect(subjectDotColor("0580")).toBe("var(--grade-a)")
    expect(subjectDotColor("Physics")).toBe("var(--md-primary)")
    expect(subjectDotColor("Additional Maths")).toBe("var(--grade-d)")
    expect(subjectDotColor("Latin")).toBe(subjectDotColor("latin "))
    expect(subjectDotColor("Latin")).toMatch(/^var\(--/)
  })
  it("renders a decorative dot at 8px by default", () => {
    const out = renderToStaticMarkup(createElement(SubjectDot, { subject: "Physics" }))
    expect(out).toBe('<i class="rd-dot" aria-hidden="true" style="width:8px;height:8px;background:var(--md-primary)"></i>')
  })
  it("fits inside a ranked row's sub line", () => {
    const out = html(createElement(RankRow, { rank: 1, title: "Waves", sub: createElement("span", null, createElement(SubjectDot, { subject: "Physics" }), "Physics"), marksLost: 6, trend: "same" }))
    expect(out).toContain('<i class="rd-dot"')
  })
})

describe("HairRows / HairRow", () => {
  it("a labelled list of hairline rows; links get a chevron, static rows do not", () => {
    const out = html(
      createElement(HairRows, { "aria-label": "Papers" }, [
        createElement(HairRow, { key: "a", title: "Mathematics · Paper 4", sub: "61/80 · 2 days ago", to: "/r/1", trailing: "+9" }),
        createElement(HairRow, { key: "b", title: "Static" }),
      ]),
    )
    expect(out).toMatch(/^<ul class="rd-hairrows" role="list" aria-label="Papers">/)
    expect(out.match(/<li class="rd-hairrow-item">/g)).toHaveLength(2)
    expect(out).toMatch(/<a class="rd-hairrow"[^>]*href="\/r\/1"/)
    expect(out.match(/rd-chev/g)).toHaveLength(1)
    expect(out).toContain('<div class="rd-hairrow">')
  })
  it("a selected button row says so", () => {
    const out = html(createElement(HairRow, { title: "Vectors", onClick: () => {}, selected: true }))
    expect(out).toMatch(/<button type="button" class="rd-hairrow rd-selected" aria-current="true">/)
  })
})

describe("RankRow", () => {
  it("rank, title, Assigned tag, marks lost, trend", () => {
    const out = html(createElement(RankRow, { rank: 1, title: "Vectors", sub: "Practised twice", marksLost: 9, trend: "better", assigned: true }))
    expect(out).toMatch(/<span class="rd-rank-n">1<\/span>/)
    expect(out).toContain('<em class="rd-tag">Assigned</em>')
    expect(out).toContain("<b>−9</b><small>marks</small>")
    expect(out).toMatch(/class="rd-trend rd-trend-better">.*Better<\/span>/)
  })
  it("a marks-lost bar sets its width and the bar layout", () => {
    const out = html(createElement(RankRow, { rank: 2, title: "Waves", marksLost: 4, trend: "worse", bar: 0.44 }))
    expect(out).toContain("rd-rank rd-rank-bar")
    expect(out).toMatch(/style="--w:44%"/)
  })
})

// Contrast of every dot token against the three surfaces it can sit on, both themes (>= 3:1, meaningful mark).
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { SUBJECT_DOT_TOKENS } from "@/components/redesign/subjects"

const INDEX_CSS = readFileSync(join(fileURLToPath(new URL("../../../", import.meta.url)), "src/index.css"), "utf8")

function tokens(theme: "light" | "dark"): Record<string, string> {
  const start = theme === "light" ? INDEX_CSS.indexOf(":root {") : INDEX_CSS.indexOf(':root[data-theme="dark"]')
  const block = INDEX_CSS.slice(start, INDEX_CSS.indexOf("\n}", start))
  return Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}
function linear(color: string): number[] {
  const hex = color.match(/^#([0-9a-f]{6})$/i)
  if (hex) return [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  const [L, C, H] = color.match(/oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)/)!.slice(1).map(Number)
  const a = C * Math.cos((H * Math.PI) / 180), b = C * Math.sin((H * Math.PI) / 180)
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map((v) => Math.min(1, Math.max(0, v)))
}
const lum = (c: number[]) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
export function contrast(a: string, b: string): number {
  const [x, y] = [lum(linear(a)), lum(linear(b))]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

describe("SubjectDot contrast", () => {
  it("goes red on a known failing token (the check can fail)", () => {
    expect(contrast(tokens("light")["--md-tertiary"], tokens("light")["--md-surface"])).toBeLessThan(3)
    expect(contrast(tokens("dark")["--grade-u"] ?? tokens("light")["--grade-u"], tokens("dark")["--md-surface-container-low"])).toBeLessThan(3)
  })
  for (const theme of ["light", "dark"] as const) {
    it(`every dot token holds 3:1 on surface, container-low and container-lowest in ${theme}`, () => {
      const t = { ...tokens("light"), ...(theme === "dark" ? tokens("dark") : {}) }
      for (const name of SUBJECT_DOT_TOKENS) {
        for (const ground of ["--md-surface", "--md-surface-container-low", "--md-surface-container-lowest"]) {
          expect(contrast(t[name], t[ground]), `${name} on ${ground} (${theme})`).toBeGreaterThanOrEqual(3)
        }
      }
    })
  }
})

/* ---- cascade: a selected row keeps its padding and fill, hovered or not ---- */
const REDESIGN_CSS = readFileSync(
  join(fileURLToPath(new URL("../../../", import.meta.url)), "src/components/redesign/redesign.css"),
  "utf8",
)

interface CssRule { selector: string; props: string[]; order: number }

function parseFlatRules(css: string): CssRule[] {
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "")
  const rules: CssRule[] = []
  let order = 0
  for (const m of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const props = m[2].split(";").map((d) => d.split(":")[0].trim()).filter(Boolean)
    for (const sel of m[1].split(",")) rules.push({ selector: sel.trim(), props, order: order++ })
  }
  return rules
}

/** Specificity of a single compound selector (no combinators), or null when it has combinators. */
function compound(sel: string) {
  if (/[\s>+~]/.test(sel)) return null
  const tag = /^[a-z][a-z0-9]*/i.exec(sel)?.[0]
  const classes = [...sel.matchAll(/\.([\w-]+)/g)].map((x) => x[1])
  const pseudos = [...sel.matchAll(/:([\w-]+)/g)].map((x) => x[1])
  return { tag, classes, pseudos, spec: [0, classes.length + pseudos.length, tag ? 1 : 0] as const }
}

function winner(rules: CssRule[], el: { tag: string; classes: string[]; hover: boolean }, prop: RegExp) {
  let best: { rule: CssRule; spec: readonly number[] } | undefined
  for (const rule of rules) {
    if (!rule.props.some((p) => prop.test(p))) continue
    const c = compound(rule.selector)
    if (!c) continue
    if (c.tag && c.tag !== el.tag) continue
    if (!c.classes.every((k) => el.classes.includes(k))) continue
    if (!c.pseudos.every((p) => p === "hover" && el.hover)) continue
    const beats =
      !best ||
      c.spec[0] > best.spec[0] ||
      (c.spec[0] === best.spec[0] && (c.spec[1] > best.spec[1] || (c.spec[1] === best.spec[1] && (c.spec[2] > best.spec[2] || (c.spec[2] === best.spec[2] && rule.order > best.rule.order)))))
    if (beats) best = { rule, spec: c.spec }
  }
  return best?.rule.selector
}

describe("selected row cascade", () => {
  const rules = parseFlatRules(REDESIGN_CSS)
  const els = [
    { tag: "button", classes: ["rd-rank", "rd-selected"] },
    { tag: "button", classes: ["rd-rank", "rd-rank-bar", "rd-selected"] },
    { tag: "button", classes: ["rd-hairrow", "rd-selected"] },
    { tag: "a", classes: ["rd-hairrow", "rd-selected"] },
    { tag: "div", classes: ["rd-hairrow", "rd-selected"] },
  ]
  for (const el of els) {
    for (const hover of [false, true]) {
      const name = `${el.tag}.${el.classes.join(".")}${hover ? ":hover" : ""}`
      if (hover && el.tag === "div") continue
      it(`${name}: padding-inline comes from a selected rule`, () => {
        expect(winner(rules, { ...el, hover }, /^padding(-inline)?$/)).toContain("rd-selected")
      })
      it(`${name}: the fill comes from a selected rule`, () => {
        expect(winner(rules, { ...el, hover }, /^background(-color)?$/)).toContain("rd-selected")
      })
    }
  }
})
