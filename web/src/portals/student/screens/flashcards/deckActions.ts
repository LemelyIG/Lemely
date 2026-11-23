import type { AddCardRequest, DeckGenerationStatus, EditCardRequest, GenerationStatusDTO } from "@/lib/flashcardTypes"
import { generationOutcome } from "./reviewView"

/**
 * What the deck screens do when a student acts, kept out of the components so it can be tested
 * without a DOM: which request a button sends, what closes when, and what the copy says. The
 * components only forward to these. A mutation is passed in as a function (react-query's `mutate`
 * fits), so a test can stand in for it.
 */

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`

/** `onSuccess` runs per call, after the server said yes. A failure runs nothing here. */
type OnSuccess = { onSuccess: () => void }

/* ── Cards (FC, add, delete) ─────────────────────────────────────────────── */

export type CardMode = "add" | "edit"
export interface CardDraft { front: string; back: string }
export interface CardSource { id: string; front: string; back: string }

export const cardSheetTitle = (mode: CardMode): string => (mode === "add" ? "New card" : "Edit card")

export const cardDraftFor = (card: Pick<CardSource, "front" | "back"> | null): CardDraft =>
  ({ front: card?.front ?? "", back: card?.back ?? "" })

export const cardSaveLabel = (mode: CardMode, pending: boolean): string =>
  pending ? (mode === "add" ? "Adding…" : "Saving…") : mode === "add" ? "Add card" : "Save"

export const cardSaveError = (mode: CardMode): string =>
  mode === "add" ? "Couldn’t add that card. Try again." : "Couldn’t save that change. Try again."

export const CARD_DELETE_ERROR = "Couldn’t delete that card. Try again."

export type CardSave =
  | { kind: "add"; body: AddCardRequest }
  | { kind: "edit"; cardId: string; body: EditCardRequest }

/**
 * The request a Save sends, or null when there is nothing to send: a blank side, an edit with no
 * card, or an edit that changes nothing (so Save stays disabled until the text really differs).
 */
export function cardSave(mode: CardMode, card: CardSource | null, draft: CardDraft): CardSave | null {
  const front = draft.front.trim()
  const back = draft.back.trim()
  if (front === "" || back === "") return null
  if (mode === "add") return { kind: "add", body: { front, back } }
  if (!card || (front === card.front.trim() && back === card.back.trim())) return null
  return { kind: "edit", cardId: card.id, body: { front, back } }
}

export interface CardMutators {
  add: (body: AddCardRequest, opts: OnSuccess) => void
  edit: (vars: { cardId: string; body: EditCardRequest }, opts: OnSuccess) => void
  remove: (cardId: string, opts: OnSuccess) => void
}

/** Sends the Save. True when a request went out; the sheet closes through `onDone` on success. */
export function submitCard(
  mode: CardMode, card: CardSource | null, draft: CardDraft, m: CardMutators, onDone: () => void,
): boolean {
  const save = cardSave(mode, card, draft)
  if (!save) return false
  if (save.kind === "add") m.add(save.body, { onSuccess: onDone })
  else m.edit({ cardId: save.cardId, body: save.body }, { onSuccess: onDone })
  return true
}

export function submitCardDelete(card: Pick<CardSource, "id">, m: CardMutators, onDone: () => void): boolean {
  m.remove(card.id, { onSuccess: onDone })
  return true
}

export interface CardDeleteConfirm { title: string; body: string; confirm: string; pending: string; keep: string }

/** The second step of Delete card: the card's own front is the consequence, Keep it is the way out. */
export const cardDeleteConfirm = (card: Pick<CardSource, "front">): CardDeleteConfirm => ({
  title: "Delete this card?",
  body: card.front,
  confirm: "Delete card",
  pending: "Deleting…",
  keep: "Keep it",
})

/* ── Delete steps (card and deck) ────────────────────────────────────────── */

export interface DeleteControls { confirmDisabled: boolean; keepDisabled: boolean; confirmLabel: string }

/**
 * What can be pressed on a delete step. While the request is in flight Keep it is held, because
 * resetting the mutation does not cancel the DELETE and the card or deck would go anyway. Once it
 * has succeeded both stay held through the exit animation: confirm would send a second DELETE, and
 * Keep it would put a deleted card's form back on screen.
 */
export function deleteControls(
  m: { isPending: boolean; isSuccess: boolean },
  labels: { confirm: string; pending: string },
): DeleteControls {
  const held = m.isPending || m.isSuccess
  return { confirmDisabled: held, keepDisabled: held, confirmLabel: m.isPending ? labels.pending : labels.confirm }
}

export type CardCloseOutcome = "dismissed" | "saved" | "deleted"

/**
 * Where focus goes when the card sheet closes. The opener (the pencil, or Add card) when it is
 * still on the page; Add card when it is gone, and always after a delete, since the pencil of a
 * card that was just deleted is about to leave the list.
 */
export function cardFocusTarget(outcome: CardCloseOutcome, openerConnected: boolean): "opener" | "add-card" {
  return outcome === "deleted" || !openerConnected ? "add-card" : "opener"
}

/* ── Rename ──────────────────────────────────────────────────────────────── */

export const DECK_TITLE_MAX = 80
export const RENAME_ERROR = "Couldn’t rename the deck. Try again."

export const renameLabel = (pending: boolean): string => (pending ? "Saving…" : "Save")

/** Save needs a valid new name and no request in flight; Cancel is held in flight so a failure is seen. */
export const renameControls = (
  m: { valid: boolean; pending: boolean },
): { saveDisabled: boolean; cancelDisabled: boolean; saveLabel: string } =>
  ({ saveDisabled: !m.valid || m.pending, cancelDisabled: m.pending, saveLabel: renameLabel(m.pending) })

/** The title to send: trimmed, 1 to 80 characters, and different from the current one. */
export function renameTitle(current: string, input: string): string | null {
  const clean = input.trim()
  if (clean === "" || clean.length > DECK_TITLE_MAX || clean === current) return null
  return clean
}

export function submitRename(
  deckId: string,
  current: string,
  input: string,
  rename: (vars: { deckId: string; title: string }, opts: OnSuccess) => void,
  onDone: () => void,
): boolean {
  const title = renameTitle(current, input)
  if (title === null) return false
  rename({ deckId, title }, { onSuccess: onDone })
  return true
}

/* ── Delete deck (FX) ────────────────────────────────────────────────────── */

export const DELETE_DECK_ERROR = "Couldn’t delete the deck. It’s still here."

export interface DeleteDeckConfirm { title: string; body: string; confirm: string; pending: string; keep: string }

/** fc.js FX: the title names the deck, the line says what goes and that it can't come back. */
export function deleteDeckConfirm(deck: { title: string; cardCount: number }): DeleteDeckConfirm {
  return {
    title: `Delete ${deck.title}?`,
    body: deck.cardCount === 0
      ? "This deck has no cards. This can’t be undone."
      : deck.cardCount === 1
        ? "The card and its progress go. This can’t be undone."
        : `All ${plural(deck.cardCount, "card")} and their progress go. This can’t be undone.`,
    confirm: "Delete deck",
    pending: "Deleting…",
    keep: "Keep it",
  }
}

/** Closes the sheet and only then tells the screen, and only once the server has deleted it. */
export function submitDeleteDeck(
  deckId: string,
  del: (deckId: string, opts: OnSuccess) => void,
  done: { onClose: () => void; onDeleted: () => void },
): void {
  del(deckId, { onSuccess: () => { done.onClose(); done.onDeleted() } })
}

/**
 * After a deck is deleted from the list's menu: the side panel gives way only when it was showing
 * that deck. Any other deck going leaves the panel where it is.
 */
export const clearsSelection = (deletedId: string, selectedId: string | null): boolean => deletedId === selectedId

/**
 * Where focus can go when the element it should return to is gone (a deleted deck's menu button,
 * a held row that left the list): the first candidate still on the page, or null.
 */
export function firstConnected<T extends { isConnected: boolean }>(...candidates: (T | null | undefined)[]): T | null {
  return candidates.find((c): c is T => !!c && c.isConnected) ?? null
}

/* ── Deck menu ───────────────────────────────────────────────────────────── */

export const DECK_MENU_ITEMS = [
  { id: "rename", label: "Rename", destructive: false },
  { id: "delete", label: "Delete deck", destructive: true },
] as const

/* ── Deck states ─────────────────────────────────────────────────────────── */

/**
 * A failed refetch over content already on screen is not an error screen: TanStack v5 leaves
 * `data` set under status "error", so the cached deck stays and a notice says it may be stale.
 */
export function keepCachedOnError<S extends "pending" | "error" | "success">(
  q: { status: S; data: unknown },
): { status: S | "success"; refreshFailed: boolean } {
  const refreshFailed = q.status === "error" && q.data !== undefined
  return { status: refreshFailed ? "success" : q.status, refreshFailed }
}

export interface GenerationToast {
  title: string
  variant: "success" | "info" | "error"
  /** Kept on the page after the toast goes, only for a deck that came back short. */
  shortfall: string | null
}

/**
 * What to say when a deck that was writing, or had failed, comes back. The real count, never the
 * requested one. Nothing before the first status has been seen, so opening a ready deck is silent.
 */
export function generationToast(
  previous: DeckGenerationStatus | undefined,
  status: GenerationStatusDTO | undefined,
): GenerationToast | null {
  if (!status || status.status !== "ready") return null
  if (previous !== "writing" && previous !== "failed") return null
  const { text, shortfall } = generationOutcome(status)
  if (status.generatedCount === 0) return { title: text, variant: "error", shortfall: null }
  return { title: text, variant: shortfall ? "info" : "success", shortfall: shortfall ? text : null }
}

/** A failed deck's retry: held while the request is in flight so a second tap cannot send a second. */
export const failedDeckView = (retrying: boolean): { retryLabel: string; retryDisabled: boolean } =>
  retrying ? { retryLabel: "Trying again…", retryDisabled: true } : { retryLabel: "Try again", retryDisabled: false }
