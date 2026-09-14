import { describe, expect, it } from "vitest"
import { isPersistableQueryKey } from "@/lib/offline/persistAllowlist"

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
