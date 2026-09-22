import { describe, expect, it } from "vitest"
import path from "node:path"
import { parsedSources, relativeTo } from "./support/jsxSource"

/*
 * C2c (Task 5) · every text-like field under `src/portals` renders through
 * the kit's `Input`/`Select`/`Textarea` rather than a hand-rolled
 * `<input>`/`<select>`/`<textarea>` (DESIGN.md §12). Checkbox, radio, file
 * and hidden inputs are a different affordance (native picker / no visible
 * chrome) and stay native by design — see `ALLOWLIST` below for the specific
 * survivors and why each one is there.
 *
 * The scan walks every `.tsx` under `src/portals`, comment-stripped so a
 * `<select>` quoted in a doc comment (several screens' module headers explain
 * *why* a field is native, in prose) is never mistaken for a live tag.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")
const PORTALS_DIR = path.join(ROOT, "src", "portals")

const EXEMPT_TYPES = ["checkbox", "radio", "file", "hidden"]

interface RawField {
  file: string
  line: number
  tag: string
  type: string | null
}

const TAG_RE = /<(input|select|textarea)\b([\s\S]*?)>/g

function findRawFields(): RawField[] {
  const found: RawField[] = []
  for (const { file, source } of parsedSources(PORTALS_DIR)) {
    const rel = relativeTo(ROOT, file)
    TAG_RE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = TAG_RE.exec(source))) {
      const tag = m[1]
      const attrs = m[2]
      const typeMatch = attrs.match(/\btype\s*=\s*["']([a-zA-Z]+)["']/)
      const line = source.slice(0, m.index).split("\n").length
      found.push({ file: rel, line, tag, type: typeMatch ? typeMatch[1] : null })
    }
  }
  return found
}

/*
 * Every survivor here is a raw field the migration intentionally leaves in
 * place, named with a one-line reason. This array started empty; the first
 * run of this test enumerated every real survivor under `src/portals`, and
 * each entry below is a genuine one (never a placeholder for unfinished
 * migration work) — anything else that shows up in `findRawFields()` fails
 * the "no un-allowlisted survivors" check further down.
 */
const ALLOWLIST: { file: string; type: string; count: number; reason: string }[] = [
  {
    file: "src/portals/teacher/screens/Grading.tsx",
    type: "file",
    count: 2,
    reason:
      "Scan and mark-scheme upload inputs — native file input keeps the OS picker; each already carries its own visible <label>.",
  },
  {
    file: "src/portals/settings/ProfileSettings.tsx",
    type: "file",
    count: 1,
    reason:
      "Avatar picker — hidden and triggered by a labelled Button, a single deliberate choice rather than a FileDrop-style zone.",
  },
  {
    file: "src/portals/teacher/screens/MarkSchemes.tsx",
    type: "file",
    count: 1,
    reason:
      "\"Upload your own\" mark scheme — hidden file input triggered by a Button, same shape as the avatar picker above.",
  },
  {
    file: "src/portals/teacher/screens/Announcements.tsx",
    type: "radio",
    count: 2,
    reason:
      "Audience radio pair (classes/school) — a native <input type=radio> pair already has full keyboard/AT semantics via its own fieldset/legend; RadioGroup's own fieldset would duplicate that structure for no behavioural gain.",
  },
  {
    file: "src/portals/auth/DeviceLimitNotice.tsx",
    type: "radio",
    count: 1,
    reason:
      "Device sign-out picker (D5.12) — each option is a whole row carrying a \"Will be signed out\" Chip and a title-bearing device name, which Radio's string-only label/description cannot express; the native input sits inside the component's own fieldset/legend and keeps full keyboard/AT semantics.",
  },
]

describe("hand-rolled form fields under src/portals", () => {
  const rawFields = findRawFields()

  it("every raw field carries an exempt type (checkbox/radio/file/hidden)", () => {
    const offenders = rawFields.filter((f) => !f.type || !EXEMPT_TYPES.includes(f.type))
    expect(offenders).toEqual([])
  })

  it("every exempt-type survivor is named in the allowlist with its real count and a reason", () => {
    for (const entry of ALLOWLIST) {
      expect(entry.reason.length, `${entry.file} (${entry.type}) needs a reason`).toBeGreaterThan(0)
      const actual = rawFields.filter((f) => f.file === entry.file && f.type === entry.type).length
      expect(actual, `${entry.file} (${entry.type})`).toBe(entry.count)
    }

    const allowlisted = ALLOWLIST.reduce((sum, e) => sum + e.count, 0)
    const survivors = rawFields.filter((f) => f.type && EXEMPT_TYPES.includes(f.type)).length
    expect(survivors, "no exempt-type survivor is missing from the allowlist").toBe(allowlisted)
  })
})
