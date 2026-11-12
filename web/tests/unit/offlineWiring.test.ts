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

  // Task 18 e2e fix: `shouldDehydrateQuery` now wires straight to
  // `shouldPersistQuery` (`lib/offline/persistAllowlist.ts`), which itself
  // requires both the allowlist AND `query.state.status === "success"` —
  // see that function's own doc comment and `persistAllowlist.test.ts` for
  // the regression this replaced `isPersistableQueryKey` alone here.
  it("dehydrates only successful, allowlisted queries via shouldPersistQuery", () => {
    expect(source).toMatch(/shouldPersistQuery/)
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

describe("AuthContext.tsx — sign-out ends the session completely (H1/H2)", () => {
  const source = read("src/lib/auth/AuthContext.tsx")

  // H1/H2 (security review): `logout` used to call `clearSession()` plus its
  // own direct `clearUploadQueue()` — the offline upload queue's clearing
  // duplicated here, and the persisted query cache never cleared at all.
  // `endSession` (`auth/storage.ts`) now owns both, alongside
  // `RequireAuth.tsx`'s stranded-session redirect and `api.ts`'s refused
  // silent refresh — see `endSession`'s own doc comment for the full guard.
  it("calls endSession, not a bare clearSession or a direct clearUploadQueue", () => {
    expect(source).toMatch(/endSession\(/)
    expect(source).not.toMatch(/clearSession\(/)
    expect(source).not.toMatch(/clearUploadQueue\(/)
  })
})

describe("storage.ts — endSession clears every session-scoped cache (H1/H2)", () => {
  const source = read("src/lib/auth/storage.ts")

  it("wires its default caches to the real query client, persister and upload queue", () => {
    expect(source).toMatch(/queryClient\.clear\(\)/)
    expect(source).toMatch(/persister\.removeClient\(\)/)
    expect(source).toMatch(/clearUploadQueue,/)
  })
})
