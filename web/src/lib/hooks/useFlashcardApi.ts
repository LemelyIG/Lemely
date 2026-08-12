import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
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
  ReviewCardRequest,
  ReviewResultDTO,
} from "@/lib/flashcardTypes"

/*
 * React-query hooks for `/api/student/flashcards/*` (S-22/S-23), following
 * `usePracticeApi.ts`'s conventions exactly: one hook per endpoint, no
 * `fallback` passed to `request()` — a real backend/auth failure surfaces as
 * a query/mutation error the screen renders, never silently resolves to
 * empty data.
 */

const DECKS_KEY = ["flashcards", "decks"] as const
const DUE_KEY = ["flashcards", "due"] as const

/** `GET /api/student/flashcards/decks` — the caller's own decks (S-22),
 * optionally narrowed to one subject. */
export function useFlashcardDecks(subjectCode?: string): UseQueryResult<DeckSummaryDTO[], Error> {
  return useQuery({
    queryKey: [...DECKS_KEY, subjectCode ?? null],
    queryFn: () =>
      request<DeckSummaryDTO[]>(
        subjectCode
          ? `/student/flashcards/decks?subject_code=${encodeURIComponent(subjectCode)}`
          : "/student/flashcards/decks",
      ),
  })
}

/** `GET /api/student/flashcards/decks/{deckId}` — one deck and every card in
 * it, in position order. */
export function useFlashcardDeck(deckId: string): UseQueryResult<DeckDetailDTO, Error> {
  return useQuery({
    queryKey: ["flashcards", "deck", deckId],
    queryFn: () => request<DeckDetailDTO>(`/student/flashcards/decks/${deckId}`),
    enabled: !!deckId,
  })
}

/**
 * `POST /api/student/flashcards/decks` — create an empty deck (manual,
 * topic-targeted, or weakness-targeted). A 409 with
 * `{"reason": "no_weaknesses"}` throws `ApiError` whose `.detail` carries
 * that reason — the caller renders the honest refusal rather than a generic
 * failure.
 */
export function useCreateDeck(): UseMutationResult<DeckSummaryDTO, Error, CreateDeckRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateDeckRequest) =>
      request<DeckSummaryDTO>("/student/flashcards/decks", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}

/**
 * `POST /api/student/flashcards/decks/generate` — an AI-generated deck for a
 * topic, or for the caller's weakest topic. The response's `generatedCount`
 * is the true persisted count and may be less than `requestedCount` — never
 * rendered as if it were the requested number.
 */
export function useGenerateDeck(): UseMutationResult<
  GenerateDeckResponseDTO,
  Error,
  GenerateDeckRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: GenerateDeckRequest) =>
      request<GenerateDeckResponseDTO>("/student/flashcards/decks/generate", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}

/** `DELETE /api/student/flashcards/decks/{deckId}` — delete one of the
 * caller's own decks, and every card in it. */
export function useDeleteDeck(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deckId: string) =>
      request<void>(`/student/flashcards/decks/${deckId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}

/** `POST /api/student/flashcards/decks/{deckId}/cards` — add a card the
 * student wrote themselves; always lands `source: "manual"`. */
export function useAddCard(
  deckId: string,
): UseMutationResult<CardDTO, Error, AddCardRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AddCardRequest) =>
      request<CardDTO>(`/student/flashcards/decks/${deckId}/cards`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["flashcards", "deck", deckId] })
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}

/** `PATCH /api/student/flashcards/cards/{cardId}` — reword a card. No
 * `source` field exists on the request; rewording an AI card never
 * relabels it as the student's own. */
export function useEditCard(
  deckId: string,
): UseMutationResult<CardDTO, Error, { cardId: string; body: EditCardRequest }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cardId, body }) =>
      request<CardDTO>(`/student/flashcards/cards/${cardId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["flashcards", "deck", deckId] })
    },
  })
}

/** `DELETE /api/student/flashcards/cards/{cardId}` — delete one of the
 * caller's own cards. */
export function useDeleteCard(
  deckId: string,
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (cardId: string) =>
      request<void>(`/student/flashcards/cards/${cardId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["flashcards", "deck", deckId] })
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}

/**
 * `GET /api/student/flashcards/due` — the cards due now, the whole backlog
 * size, and the next due time (S-22/S-23). An empty `cards` list is a real,
 * successful state — S-22's "nothing due today" — never treated as an
 * error.
 */
export function useDueSession(
  subjectCode?: string,
  limit?: number,
): UseQueryResult<DueSessionDTO, Error> {
  const query = new URLSearchParams()
  if (subjectCode) query.set("subject_code", subjectCode)
  if (limit) query.set("limit", String(limit))
  const qs = query.toString()
  return useQuery({
    queryKey: [...DUE_KEY, subjectCode ?? null, limit ?? null],
    queryFn: () => request<DueSessionDTO>(`/student/flashcards/due${qs ? `?${qs}` : ""}`),
  })
}

/**
 * `POST /api/student/flashcards/cards/{cardId}/review` — grade one card and
 * reschedule it through the SM-2 scheduler. The response carries the
 * interval before and after so the effect of the grade is visible.
 */
export function useReviewCard(): UseMutationResult<
  ReviewResultDTO,
  Error,
  { cardId: string; grade: ReviewCardRequest["grade"] }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cardId, grade }) =>
      request<ReviewResultDTO>(`/student/flashcards/cards/${cardId}/review`, {
        method: "POST",
        body: JSON.stringify({ grade } satisfies ReviewCardRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DUE_KEY })
      queryClient.invalidateQueries({ queryKey: DECKS_KEY })
    },
  })
}
