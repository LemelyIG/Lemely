import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { isPersistableQueryKey, shouldPersistQuery } from "@/lib/offline/persistAllowlist"
import { tutoringKeys } from "@/lib/tutoring/queryKeys"

/**
 * Task 10 (B6b). The allowlist's literal segments are re-grepped from the
 * real hooks (`useReferenceApi.ts`, `useLeaderboardApi.ts`'s `CLASSES_KEY`,
 * `useAnnouncementApi.ts`, `useNotificationApi.ts`, `useFlashcardApi.ts`'s
 * `DECKS_KEY`, `useTeacherApi.ts`, `useMeApi.ts`'s `PROFILE_KEY`) rather than
 * the plan's own shorthand, so this test pins the actual on-the-wire keys —
 * not a paraphrase of them.
 */
describe("isPersistableQueryKey", () => {
  it("allows the reference catalogue", () => {
    expect(isPersistableQueryKey(["reference"])).toBe(true)
  })

  it("allows the student's class list", () => {
    expect(isPersistableQueryKey(["student", "classes"])).toBe(true)
  })

  it("allows student announcements, including the unread-count child key", () => {
    expect(isPersistableQueryKey(["student", "announcements"])).toBe(true)
    expect(isPersistableQueryKey(["student", "announcements", "unread-count"])).toBe(true)
  })

  it("allows the role-agnostic notifications inbox and its children", () => {
    expect(isPersistableQueryKey(["notifications"])).toBe(true)
    expect(isPersistableQueryKey(["notifications", "counts"])).toBe(true)
    expect(isPersistableQueryKey(["notifications", "push", "config"])).toBe(true)
  })

  it("allows the flashcard decks list but not the due queue or a single deck", () => {
    expect(isPersistableQueryKey(["flashcards", "decks"])).toBe(true)
    expect(isPersistableQueryKey(["flashcards", "due"])).toBe(false)
    expect(isPersistableQueryKey(["flashcards", "deck", "d1"])).toBe(false)
  })

  it("allows the teacher's class list", () => {
    expect(isPersistableQueryKey(["teacher", "classes"])).toBe(true)
  })

  it("allows the signed-in profile", () => {
    expect(isPersistableQueryKey(["me", "profile"])).toBe(true)
  })

  it("never persists grades or live marking state", () => {
    expect(isPersistableQueryKey(["student", "overview"])).toBe(false)
    expect(isPersistableQueryKey(["student", "subject", "MATH"])).toBe(false)
    expect(isPersistableQueryKey(["student", "result", "p1"])).toBe(false)
    expect(isPersistableQueryKey(["teacher", "review", "queue", null, null, null])).toBe(false)
  })

  it("never persists a key with no matching allowlist entry", () => {
    expect(isPersistableQueryKey(["student", "exam-calendar"])).toBe(false)
    expect(isPersistableQueryKey(["teacher", "overview"])).toBe(false)
    expect(isPersistableQueryKey(["me", "student-profile"])).toBe(false)
    expect(isPersistableQueryKey([])).toBe(false)
  })
})

/**
 * Task 18 e2e fix. Regression for the bug `shouldPersistQuery`'s own doc
 * comment describes: `main.tsx`'s `shouldDehydrateQuery` override checked
 * only the allowlisted key, not tanstack's own default `status ===
 * "success"` guard, so a still-`"pending"` (or `"error"`) query with an
 * allowlisted key got dehydrated mid-flight and corrupted the next
 * `restoreClient` hydrate on an ordinary page load. Calling the real
 * `shouldPersistQuery` this test imports through a reverted, allowlist-only
 * version of the predicate (`query.state.status === "success"` removed) —
 * the pre-fix behaviour — makes the "never persists a pending/errored
 * query" cases below fail, and the current, fixed export passes them.
 */
describe("shouldPersistQuery", () => {
  it("persists a successful query with an allowlisted key", () => {
    expect(shouldPersistQuery({ queryKey: ["reference"], state: { status: "success" } })).toBe(
      true,
    )
    expect(
      shouldPersistQuery({ queryKey: ["teacher", "classes"], state: { status: "success" } }),
    ).toBe(true)
  })

  it("never persists a pending query, even with an allowlisted key", () => {
    expect(shouldPersistQuery({ queryKey: ["reference"], state: { status: "pending" } })).toBe(
      false,
    )
    expect(
      shouldPersistQuery({ queryKey: ["notifications"], state: { status: "pending" } }),
    ).toBe(false)
  })

  it("never persists an errored query, even with an allowlisted key", () => {
    expect(shouldPersistQuery({ queryKey: ["me", "profile"], state: { status: "error" } })).toBe(
      false,
    )
  })

  it("never persists a successful query with no matching allowlist entry", () => {
    expect(
      shouldPersistQuery({ queryKey: ["student", "overview"], state: { status: "success" } }),
    ).toBe(false)
  })
})

/**
 * T11 (SPEC §b.5, F32). Every tutoring response is `private, no-store`: a
 * booking carries a meeting link, a grant names who may read a child's marks.
 * None of it may be written to IndexedDB, so no tutoring key may match an
 * allowlist prefix. Checked three ways, so the test cannot pass by only
 * looking where the allowlist is not: the keys the hooks really use, the root
 * every one of them shares, and the allowlist's own source text.
 */
describe("excludes tutoring query keys", () => {
  const factories = tutoringKeys as unknown as Record<string, unknown>
  const names = Object.keys(factories)

  /** Every key the module can build, functions called with sample ids. */
  const keys: (readonly unknown[])[] = names.map((name) => {
    const value = factories[name]
    return typeof value === "function"
      ? (value as (...args: string[]) => readonly unknown[])("id-1", "id-2", "id-3")
      : (value as readonly unknown[])
  })

  it("enumerates a meaningful number of keys (at least 35)", () => {
    expect(keys.length).toBeGreaterThanOrEqual(35)
  })

  it("never persists any key tutoringKeys builds", () => {
    for (const [i, key] of keys.entries()) {
      expect(isPersistableQueryKey(key), names[i]).toBe(false)
    }
  })

  it("never persists the tutoring root or a successful tutoring query", () => {
    expect(isPersistableQueryKey(["tutoring"])).toBe(false)
    for (const [i, key] of keys.entries()) {
      expect(shouldPersistQuery({ queryKey: key, state: { status: "success" } }), names[i]).toBe(false)
    }
  })

  it("keeps the tutoring root out of the allowlist's source", () => {
    const source = readFileSync(
      join(import.meta.dirname, "..", "..", "src", "lib", "offline", "persistAllowlist.ts"),
      "utf8",
    )
    const entries = source.slice(source.indexOf("const ALLOWLIST"), source.indexOf("/** Whether a query key"))
    expect(entries.match(/\[/g)?.length ?? 0).toBeGreaterThan(7)
    expect(entries).not.toMatch(/tutor/i)
  })
})
