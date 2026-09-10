import { describe, expect, it } from "vitest"
import {
  runChecks,
  // @ts-expect-error — plain .mjs gate script, no type declarations by design.
} from "../../scripts/check-native-invariants.mjs"

/*
 * Packet A8 — pins `scripts/check-native-invariants.mjs`'s `runChecks`
 * against fixture strings, one deliberately-failing fixture per assertion.
 * The script's own CLI wrapper reads the real files and calls this same
 * function; `npm run check:native` (wired into `npm run lint`) is what
 * actually enforces these against the live tree.
 */

interface Check {
  name: string
  pass: boolean
  detail?: string
}

/** Typed wrapper around the untyped `.mjs` import (see the `@ts-expect-error`
 * above) — one cast in one place, rather than an explicit `any` on every
 * `.find((c) => ...)` callback below. */
function run(input: unknown): { checks: Check[]; passed: boolean } {
  return runChecks(input)
}

const GOOD_HTML =
  '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content" />' +
  '<meta name="apple-mobile-web-app-status-bar-style" content="default" />'

const GOOD_CSS = `
html,
body {
  overflow-x: clip;
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior-y: contain;
}

@media (pointer: coarse) {
  textarea {
    touch-action: manipulation;
  }
}

.lm-scroll {
  overscroll-behavior: contain;
}

:root {
  --fs-field: 16px;
}

.lm-app-header {
  padding-top: var(--lm-app-header-pt, 0px);
}

@media (display-mode: standalone) {
  .lm-app-header {
    padding-top: calc(var(--lm-app-header-pt, 0px) + env(safe-area-inset-top));
  }
}

.lm-app-header-pt-4 {
  --lm-app-header-pt: calc(var(--spacing) * 4);
}

.lm-app-header-pt-2\\.5 {
  --lm-app-header-pt: calc(var(--spacing) * 2.5);
}
`

const GOOD_INPUT_TSX = `export const Input = () => <input className="text-field" />`
const GOOD_TEXTAREA_TSX = `export const Textarea = () => <textarea className="text-field" />`

const GOOD_SW_SOURCE = `
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting()
})
`

const NAV_CHROME_FILE = `<div className="lm-nav-chrome">chrome</div>`
const NAV_DRAWER_FILE = `
  <div className="lm-nav-chrome">panel</div>
  <button className="lm-nav-chrome">trigger</button>
`

const GOOD_FILES: Record<string, string> = {
  "components/ui/input.tsx": GOOD_INPUT_TSX,
  "components/ui/textarea.tsx": GOOD_TEXTAREA_TSX,
  "components/ui/button.tsx": `
    <button onClick={onClick} className="hover:bg-accent active:scale-[0.98]">
      Click
    </button>
  `,
  "components/ui/nav-drawer.tsx": NAV_DRAWER_FILE,
  "components/ui/nav-shells.tsx": NAV_CHROME_FILE,
  "portals/student/index.tsx": `<main className="min-h-dvh flex flex-col">${NAV_CHROME_FILE}`,
  "portals/teacher/index.tsx": NAV_CHROME_FILE,
  "portals/admin/index.tsx": NAV_CHROME_FILE,
  "portals/marketing/index.tsx": NAV_CHROME_FILE,
  "routes.tsx": `export const routes = []`,
}

function goodInput() {
  return {
    indexHtml: GOOD_HTML,
    indexCss: GOOD_CSS,
    inputTsx: GOOD_INPUT_TSX,
    textareaTsx: GOOD_TEXTAREA_TSX,
    swSource: GOOD_SW_SOURCE,
    files: { ...GOOD_FILES },
  }
}

describe("runChecks — the happy path", () => {
  it("passes every check on well-formed fixtures", () => {
    const result = run(goodInput())
    const failures = result.checks.filter((c) => !c.pass)
    expect(failures).toEqual([])
    expect(result.passed).toBe(true)
  })
})

describe("runChecks — viewport meta", () => {
  it("fails when viewport-fit=cover is missing", () => {
    const input = goodInput()
    input.indexHtml = '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
    const result = run(input)
    expect(result.passed).toBe(false)
    expect(result.checks.find((c) => c.name.includes("viewport"))?.pass).toBe(false)
  })
})

describe("runChecks — html, body base rule", () => {
  it("fails when overflow-x: clip is missing", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("overflow-x: clip;\n  ", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("overflow-x: clip"))?.pass).toBe(false)
  })

  it("fails when -webkit-tap-highlight-color is missing", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("-webkit-tap-highlight-color: transparent;\n  ", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("tap-highlight"))?.pass).toBe(false)
  })

  it("fails when overscroll-behavior-y: contain is missing", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("overscroll-behavior-y: contain;\n", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("overscroll-behavior-y"))?.pass).toBe(false)
  })
})

describe("runChecks — (pointer: coarse)", () => {
  it("fails when touch-action: manipulation is missing from the block", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("touch-action: manipulation;\n", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("touch-action"))?.pass).toBe(false)
  })

  it("fails when touch-action: manipulation is only present outside the block (regex scoping)", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("touch-action: manipulation;\n", "")
    // Placed in an unrelated later rule — a properly scoped check must not
    // credit this as satisfying the @media (pointer: coarse) requirement.
    input.indexCss += "\n.unrelated-rule {\n  touch-action: manipulation;\n}\n"
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("touch-action"))?.pass).toBe(false)
  })
})

describe("runChecks — .lm-scroll", () => {
  it("fails when .lm-scroll has no overscroll-behavior: contain", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(".lm-scroll {\n  overscroll-behavior: contain;\n}", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("lm-scroll"))?.pass).toBe(false)
  })
})

describe("runChecks — --fs-field token", () => {
  it("fails when the token is absent", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("--fs-field: 16px;\n", "")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("fs-field"))?.pass).toBe(false)
  })

  it("fails when the token has a different value", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace("--fs-field: 16px;", "--fs-field: 14px;")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("fs-field"))?.pass).toBe(false)
  })
})

describe("runChecks — safe-area insets", () => {
  it("fails when no env(safe-area-inset-*) appears anywhere", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(/env\(safe-area-inset-top\)/g, "0px")
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("safe-area-inset"))?.pass).toBe(false)
  })

  it("fails when no @media (display-mode: standalone) block exists", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(
      /@media \(display-mode: standalone\) \{[\s\S]*?\n\}\n/,
      "",
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("standalone"))?.pass).toBe(false)
  })
})

describe("runChecks — .lm-app-header additive inset", () => {
  it("fails when there aren't exactly two .lm-app-header blocks", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(
      /@media \(display-mode: standalone\) \{[\s\S]*?\n\}\n/,
      "",
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes(".lm-app-header inset"))?.pass).toBe(false)
  })

  it("fails when the base rule uses a fixed value instead of the custom property", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(
      "padding-top: var(--lm-app-header-pt, 0px);",
      "padding-top: 16px;",
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes(".lm-app-header inset"))?.pass).toBe(false)
  })

  it("fails when the standalone rule doesn't add the safe-area inset", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(
      "padding-top: calc(var(--lm-app-header-pt, 0px) + env(safe-area-inset-top));",
      "padding-top: env(safe-area-inset-top);",
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes(".lm-app-header inset"))?.pass).toBe(false)
  })
})

describe("runChecks — .lm-app-header-pt-* named utilities", () => {
  it("fails when the pt-4 utility is missing", () => {
    const input = goodInput()
    input.indexCss = input.indexCss.replace(
      ".lm-app-header-pt-4 {\n  --lm-app-header-pt: calc(var(--spacing) * 4);\n}\n",
      "",
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("named utilities"))?.pass).toBe(false)
  })
})

describe("runChecks — text-field on native form elements", () => {
  it("fails when input.tsx uses text-body-md on the native element", () => {
    const input = goodInput()
    input.inputTsx = `export const Input = () => <input className="text-body-md" />`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("input.tsx"))?.pass).toBe(false)
  })

  it("fails when input.tsx drops text-field entirely (no text-body-md either)", () => {
    const input = goodInput()
    input.inputTsx = `export const Input = () => <input className="text-sm" />`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("input.tsx"))?.pass).toBe(false)
  })

  it("fails when textarea.tsx uses text-body-md on the native element", () => {
    const input = goodInput()
    input.textareaTsx = `export const Textarea = () => <textarea className="text-body-md" />`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("textarea.tsx"))?.pass).toBe(false)
  })

  it("fails when textarea.tsx drops text-field entirely (no text-body-md either)", () => {
    const input = goodInput()
    input.textareaTsx = `export const Textarea = () => <textarea className="text-sm" />`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("textarea.tsx"))?.pass).toBe(false)
  })
})

describe("runChecks — no class-list min-h-screen outside an <aside>", () => {
  it("fails when a file has min-h-screen in its class list", () => {
    const input = goodInput()
    input.files["portals/teacher/index.tsx"] = `<main className="min-h-screen flex flex-col">`
    const result = run(input)
    const check = result.checks.find((c) => c.name.includes("min-h-screen"))
    expect(check?.pass).toBe(false)
    expect(check?.detail).toContain("portals/teacher/index.tsx")
  })

  it("still fails when min-h-dvh is ALSO present on the same line — there is no pairing exemption", () => {
    // The exact regression this check exists to catch: Tailwind v4 emits
    // .min-h-screen after .min-h-dvh regardless of source order, both at
    // equal specificity with neither behind @media/@supports, so
    // min-h-screen always wins the cascade — "paired with min-h-dvh" is not
    // a fix, it's the bug.
    const input = goodInput()
    input.files["portals/teacher/index.tsx"] = `<main className="min-h-screen min-h-dvh flex" />`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("min-h-screen"))?.pass).toBe(false)
  })

  it("passes when min-h-screen is inside an <aside> sidebar", () => {
    const input = goodInput()
    input.files["portals/teacher/index.tsx"] = `<aside className="min-h-screen">`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("min-h-screen"))?.pass).toBe(true)
  })

  it("passes when min-h-screen is only mentioned in a comment", () => {
    const input = goodInput()
    input.files["portals/teacher/index.tsx"] = `// min-h-screen is banned, use min-h-dvh instead`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("min-h-screen"))?.pass).toBe(true)
  })
})

describe("runChecks — hover: requires active: on the same element", () => {
  it("fails when a ui component has onClick + hover: but no active:", () => {
    const input = goodInput()
    input.files["components/ui/button.tsx"] = `<button onClick={onClick} className="hover:bg-accent">Click</button>`
    const result = run(input)
    const check = result.checks.find((c) => c.name.includes("also has active:"))
    expect(check?.pass).toBe(false)
    expect(check?.detail).toContain("components/ui/button.tsx")
  })

  it("fails per-element: a second onClick+hover: element with no active: is caught even when the file has active: elsewhere", () => {
    const input = goodInput()
    input.files["components/ui/button.tsx"] = `
      <button onClick={a} className="hover:bg-accent active:scale-[0.98]">A</button>
      <button onClick={b} className="hover:bg-danger">B</button>
    `
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("also has active:"))?.pass).toBe(false)
  })

  it("passes when hover: and active: are split across a cn(...) call on the same tag", () => {
    const input = goodInput()
    input.files["components/ui/button.tsx"] =
      `<button onClick={onClick} className={cn("base", "hover:bg-accent", "active:scale-[0.98]")}>Click</button>`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("also has active:"))?.pass).toBe(true)
  })
})

describe("runChecks — lm-nav-chrome coverage", () => {
  it("fails when a chrome file is missing lm-nav-chrome", () => {
    const input = goodInput()
    input.files["portals/teacher/index.tsx"] = `<div>no chrome class here</div>`
    const result = run(input)
    const check = result.checks.find((c) => c.name.includes("lm-nav-chrome"))
    expect(check?.pass).toBe(false)
    expect(check?.detail).toContain("portals/teacher/index.tsx")
  })

  it("fails when nav-drawer.tsx applies lm-nav-chrome only once instead of twice", () => {
    const input = goodInput()
    input.files["components/ui/nav-drawer.tsx"] = `<div className="lm-nav-chrome">panel only</div>`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("lm-nav-chrome"))?.pass).toBe(false)
  })
})

describe("runChecks — apple-mobile-web-app-status-bar-style", () => {
  it("fails when it's black-translucent instead of default", () => {
    const input = goodInput()
    input.indexHtml = input.indexHtml.replace(
      '<meta name="apple-mobile-web-app-status-bar-style" content="default" />',
      '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />',
    )
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("status-bar-style"))?.pass).toBe(false)
  })
})

describe("runChecks — sw.ts skipWaiting must never run at module scope", () => {
  it("fails when self.skipWaiting() is unconditional, outside any block", () => {
    const input = goodInput()
    input.swSource = `self.skipWaiting().catch(() => {})`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("skipWaiting"))?.pass).toBe(false)
  })

  it("fails on a bare skipWaiting() imported from workbox-core at module scope", () => {
    const input = goodInput()
    input.swSource = `import { skipWaiting } from "workbox-core"\nskipWaiting()`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("skipWaiting"))?.pass).toBe(false)
  })

  it("passes a destructured message-listener param without a false brace-matching failure", () => {
    const input = goodInput()
    input.swSource = `
self.addEventListener("message", ({ data }) => {
  if (data?.type === "SKIP_WAITING") self.skipWaiting()
})`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("skipWaiting"))?.pass).toBe(true)
  })

  it("does not false-pass a module-scope call just because a comment nearby contains a stray brace", () => {
    const input = goodInput()
    input.swSource = `
// a commented-out listener: self.addEventListener("message", () => { ... })
self.skipWaiting()`
    const result = run(input)
    expect(result.checks.find((c) => c.name.includes("skipWaiting"))?.pass).toBe(false)
  })
})

describe("runChecks — --phase-b gated checks", () => {
  it("are skipped (not present in the results) when phaseB is not passed", () => {
    const result = run(goodInput())
    expect(result.checks.find((c) => c.name.includes("RouteFallback"))).toBeUndefined()
    expect(result.checks.find((c) => c.name.includes("body.style.overflow"))).toBeUndefined()
  })

  it("fail when routes.tsx still has fallback={<RouteFallback and phaseB is true", () => {
    const input = goodInput()
    input.files["routes.tsx"] = `element: <Suspense fallback={<RouteFallback />}><X /></Suspense>`
    const result = run({ ...input, phaseB: true })
    expect(result.checks.find((c) => c.name.includes("RouteFallback"))?.pass).toBe(false)
  })

  it("fail when any file sets document.body.style.overflow = \"hidden\" and phaseB is true", () => {
    const input = goodInput()
    input.files["components/ui/modal.tsx"] = `document.body.style.overflow = "hidden"`
    const result = run({ ...input, phaseB: true })
    expect(result.checks.find((c) => c.name.includes("body.style.overflow"))?.pass).toBe(false)
  })

  it("pass when phaseB is true and the tree is already clean", () => {
    const result = run({ ...goodInput(), phaseB: true })
    expect(result.passed).toBe(true)
  })
})
