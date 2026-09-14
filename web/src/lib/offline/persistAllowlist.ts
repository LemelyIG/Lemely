/*
 * Task 10 (B6b) — which react-query keys are allowed to survive a reload via
 * the persisted cache (`queryPersister.ts`, wired into `main.tsx`'s
 * `PersistQueryClientProvider`).
 *
 * An allowlist, not a denylist: grades, an active marking run, and the
 * review queue must NEVER be served stale after a reload — a wrong number on
 * a report card is not a convenience the way a slightly-stale class list is.
 * Defaulting new query keys to "not persisted" means a hook added later that
 * nobody remembered to think about here fails safe.
 *
 * Every prefix below is the real literal `queryKey` array from its owning
 * hook — re-grepped from `useReferenceApi.ts`, `useLeaderboardApi.ts`
 * (`CLASSES_KEY`), `useAnnouncementApi.ts`, `useNotificationApi.ts`,
 * `useFlashcardApi.ts` (`DECKS_KEY`), `useTeacherApi.ts` and `useMeApi.ts`
 * (`PROFILE_KEY`), not the plan's own shorthand — so this list and the hooks
 * cannot drift without `persistAllowlist.test.ts` (a source-text extraction
 * of each hook's `queryKey`) catching it.
 */
const ALLOWLIST: readonly (readonly unknown[])[] = [
  ["reference"],
  ["student", "classes"],
  ["student", "announcements"],
  ["notifications"],
  ["flashcards", "decks"],
  ["teacher", "classes"],
  ["me", "profile"],
]

/** Whether a query key starts with one of the allowlisted prefixes above. A
 * prefix match, not an exact one: `["notifications", "counts"]` persists
 * because it starts with `["notifications"]`, but `["flashcards", "deck",
 * id]` (a single deck) does not persist even though `["flashcards",
 * "decks"]` (the list) does — they share no common prefix. */
export function isPersistableQueryKey(key: readonly unknown[]): boolean {
  return ALLOWLIST.some(
    (prefix) => prefix.length <= key.length && prefix.every((segment, i) => key[i] === segment),
  )
}
