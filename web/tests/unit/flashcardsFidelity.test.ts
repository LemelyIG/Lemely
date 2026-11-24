import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles, stripComments } from "./support/jsxSource"

/*
 * L10 Task 16 · fidelity drift that no render-free test sees.
 *
 * Three rules in `src/index.css` are unlayered, so they beat every Tailwind utility (which is layered)
 * whatever the value. Each one quietly undid a flashcards design value, and each looked right in a
 * source review:
 *
 *   - `@media (pointer: coarse) { button, [role="button"] { min-block-size: 44px } }` capped every
 *     `min-h-[50px]` and `min-h-[62px]` control at 44px on a phone. The mock's buttons are 54px and the
 *     grade buttons 62px. Only `!min-h-[Npx]` (important) wins.
 *   - `:focus-visible { border-radius: 2px }` took the 28px review card down to a 2px corner the moment a
 *     keyboard user pressed Space. `focus-visible:rounded-[28px]` could never win; `focus-visible:!rounded-[28px]` does.
 *   - The shell's native frame already draws the page title as a large title, so a screen heading that
 *     repeats it must be `PageHeading repeatsTitle` (`native:sr-only`), never a bare `<h1>`.
 */

const SCREENS = join(process.cwd(), "src/portals/student/screens/flashcards")
const files = sourceFiles(SCREENS).map((file) => ({
  name: relativeTo(process.cwd(), file),
  source: stripComments(readFileSync(file, "utf8")),
}))

describe("flashcards fidelity guards", () => {
  it("every control floor above the 44px touch floor is important, or the touch rule caps it", () => {
    const capped: string[] = []
    for (const { name, source } of files) {
      for (const m of source.matchAll(/(!?)min-h-\[(\d+)px\]/g)) {
        const px = Number(m[2])
        // 45..99 is a control height. Larger values are container floors (the 320px card stage).
        if (px > 44 && px < 100 && m[1] !== "!") capped.push(`${name}: min-h-[${px}px]`)
      }
    }
    expect(capped).toEqual([])
  })

  it("a focus radius is important, or the global :focus-visible 2px radius wins", () => {
    const squared: string[] = []
    for (const { name, source } of files) {
      for (const m of source.matchAll(/focus-visible:(!?)rounded-\[\d+px\]/g)) {
        if (m[1] !== "!") squared.push(`${name}: ${m[0]}`)
      }
    }
    expect(squared).toEqual([])
  })

  it("the shelf heading is a PageHeading that repeats the shell title, not a bare h1", () => {
    const shelf = files.find((f) => f.name.endsWith("flashcards/FlashcardsScreen.tsx"))
    expect(shelf).toBeDefined()
    expect(shelf!.source).toMatch(/<PageHeading repeatsTitle[^>]*data-fc-heading/)
    expect(shelf!.source).not.toMatch(/<h1[\s>]/)
  })

  it("the unlayered rules these guards answer to are still in index.css", () => {
    const css = readFileSync(join(process.cwd(), "src/index.css"), "utf8")
    expect(css).toMatch(/@media \(pointer: coarse\)[\s\S]{0,400}min-block-size: 44px/)
    expect(css).toMatch(/:focus-visible \{[^}]*border-radius: 2px/)
  })
})
