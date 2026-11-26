import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * A teacher screen that writes to an adopted route must know about the acting role. Without it an
 * assistant whose role lacks the permission gets a live button that can only answer 403. This
 * catches the next screen someone adds, which is how the ones before it were missed.
 *
 * It is a source scan, in the same spirit as the repo's other invariants tests: it cannot prove a
 * gate is on the right control, only that the screen thought about it at all. The DOM tests in
 * `actingTeacher.dom.test.tsx` prove the gate itself works.
 */

const SCREENS = join(import.meta.dirname, "../../src/portals/teacher/screens")

/** Screens whose writes are not on a lead's data, so acting does not change them. */
const OWN_DATA = new Map([
  ["MarkSchemes.tsx", "mark schemes are a shared corpus (`POST /schemes`), not adopted"],
  ["Notifications.tsx", "the caller's own notification inbox"],
])

/** The redesigned review queue lives in a subfolder, so the scan reads that folder too; other subfolders are not scanned here. */
const SCANNED_DIRS = ["", "review"]
const files = SCANNED_DIRS.flatMap((dir) =>
  readdirSync(join(SCREENS, dir))
    .filter((f) => f.endsWith(".tsx"))
    .map((f) => (dir ? `${dir}/${f}` : f)),
)

describe("teacher screens that write", () => {
  it("finds the screens", () => {
    expect(files.length).toBeGreaterThan(15)
  })

  const writers = files.filter((f) => /\.mutate(Async)?\(|uploadPaper\(/.test(readFileSync(join(SCREENS, f), "utf8")))

  it("finds the writing screens", () => {
    expect(writers).toEqual(expect.arrayContaining(["Grading.tsx", "Classes.tsx", "QuizBuilder.tsx", "review/ReviewQueue.tsx", "Announcements.tsx"]))
  })

  it.each(writers.filter((f) => !OWN_DATA.has(f)))("%s reads the acting role", (file) => {
    const source = readFileSync(join(SCREENS, file), "utf8")
    expect(source).toMatch(/components\/acting\/(permission-gate|acting-state)/)
  })

  it("exempts only screens that really are not the lead's", () => {
    for (const [file, why] of OWN_DATA) {
      expect(files, `${file}: ${why}`).toContain(file)
    }
  })
})
