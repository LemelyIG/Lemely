import { useEffect, useMemo, useRef } from "react"
import {
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { flashcardApi, flashcardKeys, type DueScope } from "@/lib/flashcardApi"
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
  ReviewGrade,
  ReviewResultDTO,
  WeakTopicDTO,
} from "@/lib/flashcardTypes"

/*
 * React-query hooks for `/api/student/flashcards/*` (L10). No `fallback` on any request: a
 * real failure surfaces as an error the screen renders, never as silently empty data.
 */

/** Poll while a generated deck is writing. */
export const GENERATION_POLL_MS = 2000
const DECKS_POLL_MS = 4000

function invalidateDeckLists(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: flashcardKeys.decksRoot })
  void queryClient.invalidateQueries({ queryKey: flashcardKeys.dueRoot })
}

/** Every deck, or one subject's. Polls while any deck is still writing. */
export function useFlashcardDecks(subjectCode?: string | null): UseQueryResult<DeckSummaryDTO[], Error> {
  return useQuery({
    queryKey: flashcardKeys.decks(subjectCode),
    queryFn: () => flashcardApi.listDecks(subjectCode),
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.generationStatus === "writing") ? DECKS_POLL_MS : false,
  })
}

export function useFlashcardDeck(deckId: string): UseQueryResult<DeckDetailDTO, Error> {
  return useQuery({
    queryKey: flashcardKeys.deck(deckId),
    queryFn: () => flashcardApi.getDeck(deckId),
    enabled: !!deckId,
  })
}

export function useDueSession(scope: DueScope): UseQueryResult<DueSessionDTO, Error> {
  return useQuery({
    queryKey: flashcardKeys.due(scope),
    queryFn: () => flashcardApi.dueSession(scope),
  })
}

export function useWeakTopics(subjectCode?: string | null): UseQueryResult<WeakTopicDTO[], Error> {
  return useQuery({
    queryKey: flashcardKeys.weakTopics(subjectCode),
    queryFn: () => flashcardApi.weakTopics(subjectCode),
    staleTime: 60_000,
  })
}

/**
 * The writing status of one generated deck. It polls every 2 s while the deck is `writing`.
 * When the deck leaves `writing`, it refreshes the deck, the lists and the due session once.
 */
export function useGenerationStatus(
  deckId: string,
  enabled: boolean,
): UseQueryResult<GenerationStatusDTO, Error> {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: flashcardKeys.generation(deckId),
    queryFn: () => flashcardApi.generationStatus(deckId),
    enabled: enabled && !!deckId,
    refetchInterval: (q) => (q.state.data?.status === "writing" ? GENERATION_POLL_MS : false),
  })
  const previous = useRef<string | undefined>(undefined)
  const status = query.data?.status
  useEffect(() => {
    if (previous.current === "writing" && status && status !== "writing") {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    }
    previous.current = status
  }, [status, deckId, queryClient])
  return query
}

export function useCreateDeck(): UseMutationResult<DeckSummaryDTO, Error, CreateDeckRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.createDeck(body),
    onSuccess: () => invalidateDeckLists(queryClient),
  })
}

export function useRenameDeck(): UseMutationResult<DeckSummaryDTO, Error, { deckId: string; title: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ deckId, title }) => flashcardApi.renameDeck(deckId, { title }),
    onSuccess: (_deck, { deckId }) => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

export function useDeleteDeck(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deckId) => flashcardApi.deleteDeck(deckId),
    onSuccess: (_v, deckId) => {
      queryClient.removeQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/**
 * Writes an AI deck. The call is synchronous server-side (201): the returned deck is already
 * `ready` or `failed` (with an error code from `useGenerationStatus`), never `writing`.
 */
export function useGenerateDeck(): UseMutationResult<GenerateDeckResponseDTO, Error, GenerateDeckRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.generateDeck(body),
    onSuccess: () => invalidateDeckLists(queryClient),
  })
}

const RETRY_GENERATION_KEY = ["flashcards", "retry-generation"] as const

/** One request per deck: a second retry of a deck already in flight joins it instead of sending again. */
const retriesInFlight = new Map<string, Promise<GenerationStatusDTO>>()
function retryOnce(deckId: string): Promise<GenerationStatusDTO> {
  const live = retriesInFlight.get(deckId)
  if (live) return live
  const request = flashcardApi.retryGeneration(deckId).finally(() => retriesInFlight.delete(deckId))
  retriesInFlight.set(deckId, request)
  return request
}

/**
 * Retries a failed deck. Returns the final state (200), which seeds the generation query.
 * `onError` is a hook-level callback, so it fires for every deck's failure; a callback passed to
 * `mutate()` only fires for the latest call when several decks are retried in a row.
 */
export function useRetryGeneration(
  onError?: (error: Error, deckId: string) => void,
): UseMutationResult<GenerationStatusDTO, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: RETRY_GENERATION_KEY,
    mutationFn: retryOnce,
    onError: (error, deckId) => onError?.(error, deckId),
    onSuccess: (state, deckId) => {
      queryClient.setQueryData(flashcardKeys.generation(deckId), state)
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/**
 * Decks with a retry in flight. Read from the mutation cache rather than from one `useMutation`
 * result, which only ever describes its latest call: retry A, then B, and A is still pending.
 */
export function useRetryingDeckIds(): ReadonlySet<string> {
  const ids = useMutationState({
    filters: { mutationKey: RETRY_GENERATION_KEY, status: "pending" },
    select: (mutation) => mutation.state.variables as string,
  })
  return useMemo(() => new Set(ids), [ids])
}

export function useAddCard(deckId: string): UseMutationResult<CardDTO, Error, AddCardRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body) => flashcardApi.addCard(deckId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/** Reword a card. No `source` field exists, so an AI card never becomes "yours". */
export function useEditCard(
  deckId: string,
): UseMutationResult<CardDTO, Error, { cardId: string; body: EditCardRequest }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cardId, body }) => flashcardApi.editCard(cardId, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) }),
  })
}

export function useDeleteCard(deckId: string): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (cardId) => flashcardApi.deleteCard(cardId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
      invalidateDeckLists(queryClient)
    },
  })
}

/**
 * Options for grading one card. Grading is optimistic (the review screen moves on before this
 * settles). The query layer does not retry on its own; a failure goes straight to "ratings not
 * saved", and the banner's Retry re-sends the same `clientReviewId`, which the server replays
 * instead of grading the card (and awarding XP) a second time.
 */
export interface ReviewVariables {
  cardId: string
  grade: ReviewGrade
  clientReviewId: string
}

export function reviewCardMutationOptions(queryClient: QueryClient) {
  return {
    mutationFn: ({ cardId, grade, clientReviewId }: ReviewVariables) =>
      flashcardApi.reviewCard(cardId, grade, clientReviewId),
    retry: 0,
    onSuccess: () => invalidateDeckLists(queryClient),
  }
}

export function useReviewCard(): UseMutationResult<
  ReviewResultDTO,
  Error,
  ReviewVariables
> {
  const queryClient = useQueryClient()
  return useMutation(reviewCardMutationOptions(queryClient))
}
