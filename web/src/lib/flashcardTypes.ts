/*
 * TS interfaces mirroring `lemely/web/schemas_flashcards.py` (flashcard
 * routes, P4.6 chunk C / P4.9 chunk B). Field names are camelCase to match
 * the wire, following `practiceTypes.ts`'s convention exactly. Converters
 * live server-side in `lemely.web.routers.flashcards`; this file only
 * declares the shapes.
 */

// ── `/api/student/flashcards/*` ─────────────────────────────────────────

/** `origin` on a deck: `"manual"` (student-authored, empty until cards are
 * added), `"topic"` (targeted at a caller-supplied topic), or `"weakness"`
 * (server resolves the caller's own weakest topic — no `topic` may be
 * supplied alongside it). */
export type DeckOrigin = "manual" | "topic" | "weakness"

/** `source` on a card: `"manual"` (the student wrote it) or `"ai"`
 * (generated). Present on every `CardDTO` read, for the card's whole life —
 * see `CardDTO`'s doc comment. There is deliberately no `source` field on
 * `EditCardRequestDTO`: the API offers no way to ask for a relabel. */
export type CardSource = "manual" | "ai"

/** The four-button SM-2 grade vocabulary (`0`/`3`/`4`/`5` quality
 * server-side — no invented `1`/`2`). */
export type ReviewGrade = "again" | "hard" | "good" | "easy"

/** Body for `POST /api/student/flashcards/decks`. `topic` is required for
 * `origin: "topic"`, must be omitted for `"weakness"` (the server resolves
 * the caller's own weakest topic and rejects a caller-supplied one), and is
 * optional for `"manual"`. */
export interface CreateDeckRequest {
  subjectCode: string
  title: string
  description: string | null
  origin: DeckOrigin
  topic: string | null
}

/** Body for `POST /api/student/flashcards/decks/generate`. `origin` must be
 * `"topic"` or `"weakness"` — a manual deck has no AI content to generate
 * for. `count` is bounded 1-50 on the wire (a billed Gemini request). */
export interface GenerateDeckRequest {
  subjectCode: string
  origin: "topic" | "weakness"
  count: number
  topic: string | null
  title: string | null
}

/** Body for `POST /api/student/flashcards/decks/{deckId}/cards`. No
 * `source` field: a card added through this route is always `"manual"`. */
export interface AddCardRequest {
  front: string
  back: string
}

/** Body for `PATCH /api/student/flashcards/cards/{cardId}`. Both fields
 * optional (an omitted one is left untouched); no `source` field — see
 * `CardDTO`'s doc comment for why no relabel affordance exists. */
export interface EditCardRequest {
  front?: string
  back?: string
}

/** Body for `POST /api/student/flashcards/cards/{cardId}/review`. */
export interface ReviewCardRequest {
  grade: ReviewGrade
}

/**
 * One flashcard with its full SM-2 schedule state.
 *
 * `source` distinguishes an AI-written card from the student's own for the
 * card's whole life — every surface that renders a `CardDTO` must keep this
 * visible, not just at creation time (P4.6/P4.9 honesty rule 1).
 */
export interface CardDTO {
  id: string
  front: string
  back: string
  position: number
  source: CardSource
  sourceQuestionId: string | null
  repetitions: number
  easeFactor: number
  intervalDays: number
  lapses: number
  dueAt: string
  lastReviewedAt: string | null
}

/** One deck's list-view row (S-22). `topic` is the P4.2 `"<code> <name>"`
 * syllabus label the deck targets, `null` for a manual deck with none —
 * never back-filled with a guess. */
export interface DeckSummaryDTO {
  id: string
  subjectCode: string
  topic: string | null
  title: string
  description: string | null
  origin: DeckOrigin
  cardCount: number
  dueCount: number
  createdAt: string
}

/** A deck plus every one of its cards, in position order. */
export interface DeckDetailDTO {
  id: string
  subjectCode: string
  topic: string | null
  title: string
  description: string | null
  origin: DeckOrigin
  cards: CardDTO[]
}

/**
 * 201 response for a generated deck. `generatedCount` is the real, persisted
 * number of cards and may be less than `requestedCount` — the model is free
 * to return fewer and nothing pads the difference. The frontend must render
 * `generatedCount`, never `requestedCount`, as what actually happened
 * (P4.9 honesty rule 2).
 */
export interface GenerateDeckResponseDTO {
  deck: DeckSummaryDTO
  requestedCount: number
  generatedCount: number
}

/**
 * S-22/S-23's review session. An empty `cards` list is a real state, not an
 * error: `nextDueAt` carries *when* the next card comes due so the screen
 * can say that instead of just "nothing" (honesty rule 3). `totalDue` is the
 * whole backlog regardless of any `limit` applied to `cards` — never report
 * a capped session's size as the backlog.
 */
export interface DueSessionDTO {
  cards: CardDTO[]
  totalDue: number
  nextDueAt: string | null
}

/**
 * The outcome of grading one card — the new schedule, plus what changed.
 * `intervalBeforeDays`/`intervalAfterDays` are both returned so the student
 * can see the scheduler's effect rather than trust it (honesty rule 5's
 * "surface the change, don't discard it").
 */
export interface ReviewResultDTO {
  card: CardDTO
  reviewId: string
  grade: ReviewGrade
  intervalBeforeDays: number
  intervalAfterDays: number
}
