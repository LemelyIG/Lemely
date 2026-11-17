import { request } from "@/lib/api"
import type {
  AddCardRequest,
  CardDTO,
  CreateDeckRequest,
  DeckDetailDTO,
  DeckSummaryDTO,
  DueSessionDTO,
  EditCardRequest,
  GenerateDeckRequest,
  GenerateDeckResponseDTO,
  GenerationStatusDTO,
  RenameDeckRequest,
  ReviewGrade,
  ReviewResultDTO,
  WeakTopicDTO,
} from "@/lib/flashcardTypes"

/*
 * L10 · typed calls to `/api/student/flashcards/*`, plus the URL builders and query keys
 * the hooks share. Pure apart from `request()`, so the builders are unit-testable.
 */

export interface DueScope {
  subjectCode?: string | null
  deckId?: string | null
  limit?: number | null
}

function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value))
  }
  const qs = query.toString()
  return qs ? `${path}?${qs}` : path
}

export function decksUrl(subjectCode?: string | null): string {
  return withQuery("/student/flashcards/decks", { subject_code: subjectCode })
}

export function dueUrl(scope: DueScope): string {
  return withQuery("/student/flashcards/due", {
    subject_code: scope.subjectCode,
    deck_id: scope.deckId,
    limit: scope.limit,
  })
}

export function weakTopicsUrl(subjectCode?: string | null): string {
  return withQuery("/student/flashcards/weak-topics", { subject_code: subjectCode })
}

/** Query keys. `["flashcards","decks"]` stays the persisted prefix (persistAllowlist.ts). */
export const flashcardKeys = {
  decksRoot: ["flashcards", "decks"] as const,
  dueRoot: ["flashcards", "due"] as const,
  decks: (subjectCode?: string | null) => ["flashcards", "decks", subjectCode ?? null] as const,
  deck: (deckId: string) => ["flashcards", "deck", deckId] as const,
  due: (scope: DueScope) =>
    ["flashcards", "due", scope.subjectCode ?? null, scope.deckId ?? null, scope.limit ?? null] as const,
  weakTopics: (subjectCode?: string | null) => ["flashcards", "weak-topics", subjectCode ?? null] as const,
  generation: (deckId: string) => ["flashcards", "generation", deckId] as const,
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
})

export const flashcardApi = {
  listDecks: (subjectCode?: string | null) => request<DeckSummaryDTO[]>(decksUrl(subjectCode)),
  getDeck: (deckId: string) => request<DeckDetailDTO>(`/student/flashcards/decks/${deckId}`),
  createDeck: (body: CreateDeckRequest) =>
    request<DeckSummaryDTO>("/student/flashcards/decks", json("POST", body)),
  renameDeck: (deckId: string, body: RenameDeckRequest) =>
    request<DeckSummaryDTO>(`/student/flashcards/decks/${deckId}`, json("PATCH", body)),
  deleteDeck: (deckId: string) => request<void>(`/student/flashcards/decks/${deckId}`, json("DELETE")),
  generateDeck: (body: GenerateDeckRequest) =>
    request<GenerateDeckResponseDTO>("/student/flashcards/decks/generate", json("POST", body)),
  generationStatus: (deckId: string) =>
    request<GenerationStatusDTO>(`/student/flashcards/decks/${deckId}/generation`),
  retryGeneration: (deckId: string) =>
    request<GenerationStatusDTO>(`/student/flashcards/decks/${deckId}/generation/retry`, json("POST")),
  addCard: (deckId: string, body: AddCardRequest) =>
    request<CardDTO>(`/student/flashcards/decks/${deckId}/cards`, json("POST", body)),
  editCard: (cardId: string, body: EditCardRequest) =>
    request<CardDTO>(`/student/flashcards/cards/${cardId}`, json("PATCH", body)),
  deleteCard: (cardId: string) => request<void>(`/student/flashcards/cards/${cardId}`, json("DELETE")),
  dueSession: (scope: DueScope) => request<DueSessionDTO>(dueUrl(scope)),
  reviewCard: (cardId: string, grade: ReviewGrade) =>
    request<ReviewResultDTO>(`/student/flashcards/cards/${cardId}/review`, json("POST", { grade })),
  weakTopics: (subjectCode?: string | null) => request<WeakTopicDTO[]>(weakTopicsUrl(subjectCode)),
}
