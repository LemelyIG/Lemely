import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Task 10 (B6b) — source-text wiring pins, the same style `swSource.test.ts`
 * and `nativeMechanics.test.ts` already use for behaviour this suite's
 * jsdom-less environment cannot exercise directly (no service worker, no
 * `PersistQueryClientProvider` render tree). Each assertion names the exact
 * symbol a later regression could silently drop while every other test still
 * passes — an import removed by an editor's "organize imports", say.
 */
const ROOT = join(import.meta.dirname, "..", "..")
const read = (path: string): string => readFileSync(join(ROOT, path), "utf8")

describe("main.tsx — persisted query cache", () => {
  const source = read("src/main.tsx")

  it("wraps the app in PersistQueryClientProvider", () => {
    expect(source).toMatch(/PersistQueryClientProvider/)
  })

  it("dehydrates only allowlisted keys via isPersistableQueryKey", () => {
    expect(source).toMatch(/isPersistableQueryKey/)
  })
})

describe("sw.ts — Background Sync drain", () => {
  const source = read("src/sw.ts")

  it("imports Queue from workbox-background-sync", () => {
    expect(source).toMatch(/import\s*\{[^}]*\bQueue\b[^}]*\}\s*from\s*"workbox-background-sync"/)
  })

  it("imports drainUploadQueue from the shared offline queue module", () => {
    expect(source).toMatch(/import\s*\{[^}]*\bdrainUploadQueue\b[^}]*\}\s*from\s*"@\/lib\/offline\/uploadQueue"/)
  })
})

describe("CorrectPaper.tsx — offline enqueue and queued banner", () => {
  const source = read("src/portals/student/screens/CorrectPaper.tsx")

  it("imports enqueueUpload", () => {
    expect(source).toMatch(/enqueueUpload/)
  })

  it("imports QueuedBanner", () => {
    expect(source).toMatch(/QueuedBanner/)
  })

  it("imports shouldQueueUpload", () => {
    expect(source).toMatch(/shouldQueueUpload/)
  })
})

describe("AuthContext.tsx — sign-out clears the offline upload queue", () => {
  const source = read("src/lib/auth/AuthContext.tsx")

  it("calls clearUploadQueue", () => {
    expect(source).toMatch(/clearUploadQueue\(/)
  })
})
