import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

/*
 * C2c (Task 5) · every kit field component roots its native control in a
 * `data-kit-field` marker. `audit.mjs`'s `kit-fields` assertion (per-route,
 * post-axe) relies on this to tell a migrated field from a hand-rolled one at
 * runtime — it cannot see which React component rendered an element, only the
 * DOM the browser produced, so the marker is the only signal it has.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")
const UI_DIR = path.join(ROOT, "src", "components", "ui")

const MARKERS: { file: string; value: string }[] = [
  { file: "input.tsx", value: "input" },
  { file: "select.tsx", value: "select" },
  { file: "textarea.tsx", value: "textarea" },
  { file: "slider.tsx", value: "slider" },
  { file: "checkbox.tsx", value: "checkbox" },
  { file: "radio.tsx", value: "radio" },
]

describe("kit field components carry a data-kit-field marker", () => {
  for (const { file, value } of MARKERS) {
    it(`${file} contains data-kit-field="${value}"`, () => {
      const source = fs.readFileSync(path.join(UI_DIR, file), "utf8")
      expect(source).toContain(`data-kit-field="${value}"`)
    })
  }
})
