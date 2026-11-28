import { describe, expect, it } from "vitest"
import { decksUrl, dueUrl, flashcardKeys, weakTopicsUrl } from "@/lib/flashcardApi"
import { isPersistableQueryKey } from "@/lib/offline/persistAllowlist"

describe("flashcard URL builders", () => {
  it("lists every deck, or one subject's", () => {
    expect(decksUrl()).toBe("/student/flashcards/decks")
    expect(decksUrl("0580")).toBe("/student/flashcards/decks?subject_code=0580")
  })

  it("scopes the due session by subject, deck and limit, encoding values", () => {
    expect(dueUrl({})).toBe("/student/flashcards/due")
    expect(dueUrl({ subjectCode: "0580", deckId: "d 1", limit: 20 })).toBe(
      "/student/flashcards/due?subject_code=0580&deck_id=d+1&limit=20",
    )
  })

  it("asks for weak topics across subjects or for one", () => {
    expect(weakTopicsUrl()).toBe("/student/flashcards/weak-topics")
    expect(weakTopicsUrl("0625")).toBe("/student/flashcards/weak-topics?subject_code=0625")
  })
})

describe("flashcard query keys", () => {
  it("keeps the decks list persistable offline and the rest not", () => {
    expect(isPersistableQueryKey(flashcardKeys.decks())).toBe(true)
    expect(isPersistableQueryKey(flashcardKeys.decks("0580"))).toBe(true)
    expect(isPersistableQueryKey(flashcardKeys.deck("d1"))).toBe(false)
    expect(isPersistableQueryKey(flashcardKeys.due({}))).toBe(false)
    expect(isPersistableQueryKey(flashcardKeys.generation("d1"))).toBe(false)
  })

  it("nests every scoped key under its root so one invalidation reaches them all", () => {
    expect(flashcardKeys.decks("0580").slice(0, 2)).toEqual([...flashcardKeys.decksRoot])
    expect(flashcardKeys.due({ deckId: "d1" }).slice(0, 2)).toEqual([...flashcardKeys.dueRoot])
  })
})
