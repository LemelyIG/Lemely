import { useCallback, useEffect, useMemo, useRef } from "react"
import {
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type MutationCache,
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

/**
 * The cache once a deck is gone. It leaves every cached list first, so a screen told "deleted" cannot
 * fall back to the deck that just went (`removeQueries` and the refetch both land after that), and
 * then its own query goes. The lists are refetched to confirm.
 */
export function afterDeleteDeck(queryClient: QueryClient, deckId: string): void {
  queryClient.setQueriesData<DeckSummaryDTO[]>({ queryKey: flashcardKeys.decksRoot }, (decks) =>
    decks?.filter((d) => d.id !== deckId),
  )
  queryClient.removeQueries({ queryKey: flashcardKeys.deck(deckId) })
  invalidateDeckLists(queryClient)
}

export function useDeleteDeck(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deckId) => flashcardApi.deleteDeck(deckId),
    onSuccess: (_v, deckId) => afterDeleteDeck(queryClient, deckId),
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

type RetryMutation = ReturnType<MutationCache["getAll"]>[number]

/**
 * The request behind each retry mutation this hook started. Keyed by the Mutation object, not by deck
 * id and not module-wide: "in flight" is then whatever the QueryClient's own mutation cache still
 * holds, so `queryClient.clear()` on sign-out drops every entry with it (a retry of the same deck id in
 * the next session sends a new request) and a mutation that was cleared is recognisably orphaned.
 * A pending mutation missing from this map (restored, or started elsewhere) has no request to join.
 */
const retryRequests = new WeakMap<RetryMutation, Promise<GenerationStatusDTO>>()

const retryMutations = (cache: MutationCache) => cache.findAll({ mutationKey: RETRY_GENERATION_KEY })

/** The request of a retry this hook started for the deck and the cache still holds as pending. */
function liveRetryRequest(cache: MutationCache, deckId: string): Promise<GenerationStatusDTO> | undefined {
  for (const m of retryMutations(cache)) {
    if (m.state.status === "pending" && m.state.variables === deckId) {
      const request = retryRequests.get(m)
      if (request) return request
    }
  }
  return undefined
}

/**
 * Retries a failed deck. Returns the final state (200), which seeds the generation query.
 * A second call for a deck that is already retrying (a stale closure, a second screen instance)
 * joins the live request instead of sending another. Only the call that started the request acts on
 * its outcome (seeding the cache and refreshing the lists on success, `onError` on failure), so a
 * deck settling once has its effects once. `onError` is not passed to `mutate()`, which fires only
 * for the latest call when several decks are retried in a row. `queryClient.clear()` empties the
 * mutation cache but cannot cancel a request: an outcome that lands after it belongs to the old
 * session and is dropped, success and failure alike, so it cannot overwrite the new session's cache.
 */
export function useRetryGeneration(
  onError?: (error: Error, deckId: string) => void,
): { mutate: (deckId: string) => void } {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationKey: RETRY_GENERATION_KEY,
    mutationFn: (deckId: string) => flashcardApi.retryGeneration(deckId),
  })
  // Calls from older renders must see the latest callback and mutation without changing identity.
  const latest = useRef({ mutation, onError })
  latest.current = { mutation, onError }
  const mutateAsync = useCallback(
    (deckId: string) => {
      const cache = queryClient.getMutationCache()
      const joined = liveRetryRequest(cache, deckId)
      if (joined) return joined
      // The mutation is added to the cache synchronously, so the one that was not there before the
      // call is this call's. Looking for "a pending retry of this deck" could find a restored one.
      const before = new Set(retryMutations(cache))
      const request = latest.current.mutation.mutateAsync(deckId)
      const owner = retryMutations(cache).find((m) => !before.has(m))
      if (owner) retryRequests.set(owner, request)
      const owned = () => owner !== undefined && retryMutations(cache).includes(owner)
      const report = latest.current.onError
      request.then(
        (state) => {
          if (!owned()) return
          queryClient.setQueryData(flashcardKeys.generation(deckId), state)
          void queryClient.invalidateQueries({ queryKey: flashcardKeys.deck(deckId) })
          invalidateDeckLists(queryClient)
        },
        (error: Error) => {
          if (owned()) report?.(error, deckId)
        },
      )
      return request
    },
    [queryClient],
  )
  // Only the action is exposed: per-call callbacks and the raw mutation result could still report an
  // outcome from a session that `queryClient.clear()` has ended.
  const mutate = useCallback(
    (deckId: string) => {
      void mutateAsync(deckId).catch(() => {})
    },
    [mutateAsync],
  )
  return useMemo(() => ({ mutate }), [mutate])
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
    onSuccess: () => {
      invalidateDeckLists(queryClient)
      void queryClient.invalidateQueries({ queryKey: ["flashcards", "deck"] })
    },
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
