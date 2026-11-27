import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

const hooks = path.resolve(__dirname, "../../src/lib/hooks")
const read = (f: string) => fs.readFileSync(path.join(hooks, f), "utf8")

/** Home carries positional paper ids, so every mutation that moves papers or classes must drop it. */
const HOME = "queryKey: STUDENT_HOME_KEY"

describe("the Home query is invalidated wherever Overview is", () => {
  it.each([
    ["usePaperDeletionApi.ts", 2],
    ["useSelfReviewApi.ts", 1],
    ["useStudentApi.ts", 1],
  ])("%s invalidates STUDENT_HOME_KEY %i time(s)", (file, count) => {
    const src = read(file)
    expect(src.split(HOME).length - 1).toBe(count)
  })

  it("delete and restore await it alongside the other invalidations", () => {
    const src = read("usePaperDeletionApi.ts")
    const awaited = src.split("Promise.all([").slice(1).filter((b) => b.split("])")[0].includes(HOME))
    expect(awaited).toHaveLength(2)
  })
})
