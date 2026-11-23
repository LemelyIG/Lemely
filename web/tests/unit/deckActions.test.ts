import { describe, expect, it, vi } from "vitest"
import {
  CARD_DELETE_ERROR,
  DECK_MENU_ITEMS,
  DECK_TITLE_MAX,
  DELETE_DECK_ERROR,
  RENAME_ERROR,
  cardDeleteConfirm,
  cardDraftFor,
  cardFocusTarget,
  cardSave,
  cardSaveError,
  cardSaveLabel,
  cardSheetTitle,
  clearsSelection,
  deleteControls,
  deleteDeckConfirm,
  firstConnected,
  failedDeckView,
  generationToast,
  keepCachedOnError,
  renameControls,
  renameLabel,
  renameTitle,
  submitCard,
  submitCardDelete,
  submitDeleteDeck,
  submitRename,
  type CardMutators,
} from "@/portals/student/screens/flashcards/deckActions"
import type { GenerationStatusDTO } from "@/lib/flashcardTypes"

const card = { id: "c1", front: "Magnitude of (x, y)", back: "√(x² + y²)" }

/** Records the mutate calls; `succeed` runs the per-call onSuccess like react-query does. */
function mutators(succeed = true) {
  const m = {
    add: vi.fn((_body: unknown, o: { onSuccess: () => void }) => { if (succeed) o.onSuccess() }),
    edit: vi.fn((_vars: unknown, o: { onSuccess: () => void }) => { if (succeed) o.onSuccess() }),
    remove: vi.fn((_id: string, o: { onSuccess: () => void }) => { if (succeed) o.onSuccess() }),
  }
  return m satisfies CardMutators
}

describe("card sheet copy and draft", () => {
  it("titles the sheet by mode and starts from the card (or empty)", () => {
    expect(cardSheetTitle("add")).toBe("New card")
    expect(cardSheetTitle("edit")).toBe("Edit card")
    expect(cardDraftFor(card)).toEqual({ front: card.front, back: card.back })
    expect(cardDraftFor(null)).toEqual({ front: "", back: "" })
  })

  it("labels the save button by mode and pending", () => {
    expect(cardSaveLabel("add", false)).toBe("Add card")
    expect(cardSaveLabel("add", true)).toBe("Adding…")
    expect(cardSaveLabel("edit", false)).toBe("Save")
    expect(cardSaveLabel("edit", true)).toBe("Saving…")
  })

  it("has an error line per mode and none of the copy has an exclamation mark", () => {
    expect(cardSaveError("add")).toBe("Couldn’t add that card. Try again.")
    expect(cardSaveError("edit")).toBe("Couldn’t save that change. Try again.")
    const all = [CARD_DELETE_ERROR, RENAME_ERROR, DELETE_DECK_ERROR, cardSaveError("add"), cardSaveError("edit")]
    expect(all.join(" ")).not.toContain("!")
  })
})

describe("cardSave", () => {
  it("adds trimmed text, and refuses a blank side", () => {
    expect(cardSave("add", null, { front: "  Q ", back: " A  " })).toEqual({ kind: "add", body: { front: "Q", back: "A" } })
    expect(cardSave("add", null, { front: "Q", back: "   " })).toBeNull()
    expect(cardSave("add", null, { front: "", back: "A" })).toBeNull()
  })

  it("edits the card by id, and offers no save for an unchanged or blank edit", () => {
    expect(cardSave("edit", card, { front: card.front, back: "x" })).toEqual({
      kind: "edit", cardId: "c1", body: { front: card.front, back: "x" },
    })
    expect(cardSave("edit", card, { front: ` ${card.front} `, back: card.back })).toBeNull()
    expect(cardSave("edit", card, { front: "", back: card.back })).toBeNull()
    expect(cardSave("edit", null, { front: "Q", back: "A" })).toBeNull()
  })
})

describe("card mutation wiring", () => {
  it("add sends the trimmed body to add, then closes", () => {
    const m = mutators()
    const done = vi.fn()
    expect(submitCard("add", null, { front: " Q ", back: "A" }, m, done)).toBe(true)
    expect(m.add).toHaveBeenCalledWith({ front: "Q", back: "A" }, expect.objectContaining({ onSuccess: expect.any(Function) }))
    expect(m.edit).not.toHaveBeenCalled()
    expect(done).toHaveBeenCalledTimes(1)
  })

  it("edit sends the card id and body to edit, never to add", () => {
    const m = mutators()
    const done = vi.fn()
    expect(submitCard("edit", card, { front: card.front, back: "new" }, m, done)).toBe(true)
    expect(m.edit).toHaveBeenCalledWith({ cardId: "c1", body: { front: card.front, back: "new" } }, expect.anything())
    expect(m.add).not.toHaveBeenCalled()
    expect(done).toHaveBeenCalledTimes(1)
  })

  it("an invalid draft sends nothing and does not close", () => {
    const m = mutators()
    const done = vi.fn()
    expect(submitCard("add", null, { front: "Q", back: " " }, m, done)).toBe(false)
    expect(m.add).not.toHaveBeenCalled()
    expect(done).not.toHaveBeenCalled()
  })

  it("a failed save keeps the sheet open", () => {
    const m = mutators(false)
    const done = vi.fn()
    submitCard("add", null, { front: "Q", back: "A" }, m, done)
    expect(m.add).toHaveBeenCalledTimes(1)
    expect(done).not.toHaveBeenCalled()
  })

  it("delete sends the card id to remove, and closes only on success", () => {
    const ok = mutators()
    const done = vi.fn()
    submitCardDelete(card, ok, done)
    expect(ok.remove).toHaveBeenCalledWith("c1", expect.anything())
    expect(done).toHaveBeenCalledTimes(1)

    const bad = mutators(false)
    const done2 = vi.fn()
    submitCardDelete(card, bad, done2)
    expect(done2).not.toHaveBeenCalled()
  })
})

describe("deleting a card asks first", () => {
  it("names the card and offers Keep it", () => {
    expect(cardDeleteConfirm(card)).toEqual({
      title: "Delete this card?",
      body: card.front,
      confirm: "Delete card",
      pending: "Deleting…",
      keep: "Keep it",
    })
  })
})

describe("cardFocusTarget", () => {
  it("returns to the opener when it is still there", () => {
    expect(cardFocusTarget("dismissed", true)).toBe("opener")
    expect(cardFocusTarget("saved", true)).toBe("opener")
  })

  it("falls back to Add card when the opener is gone", () => {
    expect(cardFocusTarget("saved", false)).toBe("add-card")
    expect(cardFocusTarget("dismissed", false)).toBe("add-card")
  })

  it("never returns to the pencil of a card that was just deleted", () => {
    expect(cardFocusTarget("deleted", true)).toBe("add-card")
  })
})

describe("rename", () => {
  it("accepts a trimmed, changed title of 1 to 80 characters", () => {
    expect(renameTitle("Vectors", "  Vector drills ")).toBe("Vector drills")
    expect(DECK_TITLE_MAX).toBe(80)
    expect(renameTitle("Vectors", "x".repeat(80))).toBe("x".repeat(80))
  })

  it("refuses blank, too long, or unchanged", () => {
    expect(renameTitle("Vectors", "   ")).toBeNull()
    expect(renameTitle("Vectors", "x".repeat(81))).toBeNull()
    expect(renameTitle("Vectors", " Vectors ")).toBeNull()
  })

  it("labels the button", () => {
    expect(renameLabel(false)).toBe("Save")
    expect(renameLabel(true)).toBe("Saving…")
  })

  it("sends the deck id and the clean title, then closes on success only", () => {
    const rename = vi.fn((_v: unknown, o: { onSuccess: () => void }) => o.onSuccess())
    const done = vi.fn()
    expect(submitRename("d1", "Vectors", "  Vector drills ", rename, done)).toBe(true)
    expect(rename).toHaveBeenCalledWith({ deckId: "d1", title: "Vector drills" }, expect.anything())
    expect(done).toHaveBeenCalledTimes(1)

    const idle = vi.fn()
    expect(submitRename("d1", "Vectors", "Vectors", idle, done)).toBe(false)
    expect(idle).not.toHaveBeenCalled()

    const fail = vi.fn()
    const done2 = vi.fn()
    submitRename("d1", "Vectors", "New", fail, done2)
    expect(done2).not.toHaveBeenCalled()
  })
})

describe("delete deck", () => {
  it("says what goes and that it cannot be undone (FX)", () => {
    expect(deleteDeckConfirm({ title: "Vectors", cardCount: 18 })).toEqual({
      title: "Delete Vectors?",
      body: "All 18 cards and their progress go. This can’t be undone.",
      confirm: "Delete deck",
      pending: "Deleting…",
      keep: "Keep it",
    })
    expect(deleteDeckConfirm({ title: "V", cardCount: 1 }).body).toBe("The card and its progress go. This can’t be undone.")
    expect(deleteDeckConfirm({ title: "V", cardCount: 0 }).body).toBe("This deck has no cards. This can’t be undone.")
  })

  it("closes the sheet, then tells the screen, only after the delete succeeds", () => {
    const order: string[] = []
    const del = vi.fn((_id: string, o: { onSuccess: () => void }) => o.onSuccess())
    submitDeleteDeck("d1", del, { onClose: () => order.push("close"), onDeleted: () => order.push("deleted") })
    expect(del).toHaveBeenCalledWith("d1", expect.anything())
    expect(order).toEqual(["close", "deleted"])
  })

  it("a failed delete leaves the deck and the sheet alone", () => {
    const del = vi.fn()
    const onClose = vi.fn()
    const onDeleted = vi.fn()
    submitDeleteDeck("d1", del, { onClose, onDeleted })
    expect(onClose).not.toHaveBeenCalled()
    expect(onDeleted).not.toHaveBeenCalled()
  })
})

describe("deck menu", () => {
  it("lists Rename and Delete deck, the second marked destructive", () => {
    expect(DECK_MENU_ITEMS.map((i) => [i.id, i.label, i.destructive])).toEqual([
      ["rename", "Rename", false],
      ["delete", "Delete deck", true],
    ])
  })
})

describe("keepCachedOnError", () => {
  it("keeps cached content when a refetch fails, and flags it", () => {
    expect(keepCachedOnError({ status: "error", data: { a: 1 } })).toEqual({ status: "success", refreshFailed: true })
  })

  it("lets a first-load failure through as an error", () => {
    expect(keepCachedOnError({ status: "error", data: undefined })).toEqual({ status: "error", refreshFailed: false })
  })

  it("passes pending and success through", () => {
    expect(keepCachedOnError({ status: "pending", data: undefined })).toEqual({ status: "pending", refreshFailed: false })
    expect(keepCachedOnError({ status: "success", data: 1 })).toEqual({ status: "success", refreshFailed: false })
  })
})

describe("generationToast", () => {
  const ready = (generatedCount: number, requestedCount: number | null = 12): GenerationStatusDTO => ({
    deckId: "d", status: "ready", requestedCount, generatedCount, error: null,
  })

  it("reports the real count when a writing or failed deck becomes ready", () => {
    expect(generationToast("writing", ready(12))).toEqual({ title: "12 cards ready", variant: "success", shortfall: null })
    expect(generationToast("failed", ready(12))?.title).toBe("12 cards ready")
  })

  it("says so when fewer cards were written than asked for, and keeps the line", () => {
    expect(generationToast("writing", ready(9))).toEqual({
      title: "9 of 12 cards written", variant: "info", shortfall: "9 of 12 cards written",
    })
  })

  it("treats nothing written as an error, never as success", () => {
    expect(generationToast("writing", ready(0))?.variant).toBe("error")
  })

  it("says nothing on first load or when nothing changed", () => {
    expect(generationToast(undefined, ready(12))).toBeNull()
    expect(generationToast("ready", ready(12))).toBeNull()
    expect(generationToast("writing", { ...ready(12), status: "writing" })).toBeNull()
    expect(generationToast("writing", undefined)).toBeNull()
  })
})

describe("failedDeckView", () => {
  it("offers Try again, and holds it while the retry is in flight", () => {
    expect(failedDeckView(false)).toEqual({ retryLabel: "Try again", retryDisabled: false })
    expect(failedDeckView(true)).toEqual({ retryLabel: "Trying again…", retryDisabled: true })
  })
})

describe("deleteControls: nothing can be pressed while a delete is in flight or has landed", () => {
  const labels = { confirm: "Delete card", pending: "Deleting…" }

  it("idle: both buttons live, confirm says what it does", () => {
    expect(deleteControls({ isPending: false, isSuccess: false }, labels))
      .toEqual({ confirmDisabled: false, keepDisabled: false, confirmLabel: "Delete card" })
  })

  it("in flight: Keep it is held (a reset would not cancel the request) and confirm cannot send a second", () => {
    expect(deleteControls({ isPending: true, isSuccess: false }, labels))
      .toEqual({ confirmDisabled: true, keepDisabled: true, confirmLabel: "Deleting…" })
  })

  it("succeeded: confirm stays off through the exit animation, so no duplicate DELETE", () => {
    const c = deleteControls({ isPending: false, isSuccess: true }, labels)
    expect(c.confirmDisabled).toBe(true)
    expect(c.keepDisabled).toBe(true)
    expect(c.confirmLabel).toBe("Delete card")
  })
})

describe("renameControls", () => {
  it("Cancel is held while the rename is in flight, Save while it is invalid or in flight", () => {
    expect(renameControls({ valid: true, pending: false })).toEqual({ saveDisabled: false, cancelDisabled: false, saveLabel: "Save" })
    expect(renameControls({ valid: true, pending: true })).toEqual({ saveDisabled: true, cancelDisabled: true, saveLabel: "Saving…" })
    expect(renameControls({ valid: false, pending: false }).saveDisabled).toBe(true)
  })
})

describe("clearsSelection", () => {
  it("the side panel gives way only when the deck that went is the one it shows", () => {
    expect(clearsSelection("d1", "d1")).toBe(true)
    expect(clearsSelection("d2", "d1")).toBe(false)
    expect(clearsSelection("d2", null)).toBe(false)
  })
})

describe("firstConnected", () => {
  const live = { isConnected: true, name: "live" }
  const gone = { isConnected: false, name: "gone" }
  const other = { isConnected: true, name: "other" }

  it("skips a detached trigger and null, and lands on the first element still on the page", () => {
    expect(firstConnected(gone, null, undefined, live, other)).toBe(live)
  })

  it("is null when nothing is left", () => {
    expect(firstConnected(gone, null)).toBeNull()
    expect(firstConnected()).toBeNull()
  })
})
