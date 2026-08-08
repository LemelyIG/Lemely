/*
 * Pure data + decision logic for `QuizTaker` (S-04's reusable
 * question-rendering + answer-input surface, `lemely.core.loose_schemas.QuestionType`
 * on the wire as `questionType`). No React, no DOM — this is what
 * `web/tests/unit/quizTaker.test.ts` exercises directly, same split as
 * `onboardingData.ts`/`onboarding.test.ts`.
 */

import type { SaveAnswerRequest, StudentQuizQuestion } from "@/lib/placementTypes"

// ── Answer-input surface (UI spec S-04: "answer input appropriate to the
// question type") ───────────────────────────────────────────────────────

export type AnswerInputKind = "mcq" | "short" | "structured"

/** Question types whose real answer is a short value (a number, a formula,
 * a one-line recall) — a single-line text input, no "work it on paper"
 * affordance needed. Everything else defaults to `structured`: multi-step
 * working, a diagram/table/graph description, or free explanation, where a
 * student genuinely may work it out on paper first — for those we offer the
 * `workingText` field as that affordance (there is no photo-upload route in
 * this wire contract; camera capture is a separate PWA feature, UI spec
 * §1.5, not built here). */
const SHORT_ANSWER_TYPES = new Set(["calculation", "equation", "graph_read", "recall"])

/** Decide which answer surface a question needs. `mcqOptions` takes
 * precedence over `questionType` — a non-empty options list is the actual
 * contract for "this is multiple choice", regardless of what the taxonomy
 * label says. */
export function answerInputKind(
  questionType: string,
  mcqOptions: string[] | null,
): AnswerInputKind {
  if (mcqOptions && mcqOptions.length > 0) return "mcq"
  if (SHORT_ANSWER_TYPES.has(questionType)) return "short"
  return "structured"
}

// ── Answered / unanswered (S-04's submit warning must use the real,
// current answer state — never a stale or fabricated count) ─────────────

/** A question counts as answered once it carries a non-empty `answerText`
 * OR a non-empty `workingText` — a student who wrote out working but hasn't
 * filled in a final answer line yet has still done something, and marking
 * that as "unanswered" would nag over real effort. Whitespace-only text
 * does not count (a stray space is not an answer). */
export function isQuestionAnswered(q: {
  answerText: string | null
  workingText: string | null
}): boolean {
  return (q.answerText?.trim().length ?? 0) > 0 || (q.workingText?.trim().length ?? 0) > 0
}

/** Count of currently-unanswered questions, computed from the live local
 * answer state rather than the take payload's `header.unansweredCount`
 * snapshot — that count goes stale the moment the student answers a
 * question, and the submit warning must reflect what is actually true right
 * now, not what was true at load time. */
export function countUnanswered(
  questions: readonly { answerText: string | null; workingText: string | null }[],
): number {
  return questions.filter((q) => !isQuestionAnswered(q)).length
}

// ── Answer autosave payload ──────────────────────────────────────────────
//
// Every save — debounced edit, reconnect retry, pre-submit flush — sends
// BOTH fields, read from the cache at send time (`buildRetrySavePayload`
// below). There is deliberately no single-field variant any more.
//
// A single-field payload ("only send the key that changed", the D4.5
// onboarding rule) was correct while each edit had its own save on the
// wire. It stopped being expressible once saves are coalesced per question
// (see `SaveQueueState` below): a coalesced save stands for *several* edits,
// possibly to both fields, so there is no one "field that changed" to name.
// Sending both from the cache is safe for the reason `buildRetrySavePayload`
// documents — a cache entry always holds the question's true current state,
// seeded from the server and thereafter only ever updated by a real edit —
// so it re-asserts reality rather than clobbering an untouched field with a
// stale `null`. `SaveAnswerRequestDTO` treats an omitted field as "leave
// untouched" and a present one as "set to this", which is exactly what a
// both-fields re-assertion wants.

// ── Time display (S-04: elapsed always; remaining only when the quiz
// carries a `timeLimitMinutes` — placement's is always `null`, D4.6 §5) ──

/** `mm:ss`, or `h:mm:ss` past an hour. Negative input clamps to `0:00`. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const hours = Math.floor(s / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const seconds = s % 60
  const mm = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes)
  const ss = String(seconds).padStart(2, "0")
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

/** Seconds remaining before `timeLimitMinutes` elapses, or `null` when the
 * quiz has no time limit (every placement test) — S-04 must not invent a
 * countdown for an untimed quiz. Clamped at 0, never negative. */
export function remainingSeconds(
  timeLimitMinutes: number | null,
  elapsedSeconds: number,
): number | null {
  if (timeLimitMinutes === null) return null
  return Math.max(0, timeLimitMinutes * 60 - elapsedSeconds)
}

// ── Header display (S-04 is the reusable surface P4.9/P5 compose for
// teacher-assigned quizzes too, where `className`/`teacherName` are real —
// today's placement callers always pass `null` for both, D4.6 §3) ───────

/**
 * The optional "assigned by" line: `className` and `teacherName` joined
 * with " · " when present, `null` when neither is (every placement test).
 * Never renders an empty string or a "—" placeholder standing in for a
 * real class/teacher — the caller shows nothing at all when this is `null`.
 * Blank/whitespace-only strings are treated the same as absent, matching
 * `isQuestionAnswered`'s whitespace rule above.
 */
export function quizAffiliationLabel(
  className: string | null,
  teacherName: string | null,
): string | null {
  const parts = [className, teacherName].filter(
    (p): p is string => !!p && p.trim().length > 0,
  )
  return parts.length > 0 ? parts.join(" · ") : null
}

/** A question's topic label, or the honest "not classified" fallback for
 * `topic: null` — never the empty string, which would silently read as a
 * topic that just happens to have no name. */
export function formatQuestionTopic(topic: string | null): string {
  return topic ?? "Topic not classified"
}

// ── Question navigation ──────────────────────────────────────────────────

/** Keep a question index inside `[0, count - 1]` (or `0` for an empty set)
 * — same clamp-at-the-edges shape as onboarding's `clampStepIndex`. */
export function clampQuestionIndex(index: number, count: number): number {
  if (count <= 0) return 0
  return Math.min(Math.max(index, 0), count - 1)
}

/** Seed local per-question answer state from the take payload — the resume
 * path (UI spec S-04: "resume after leaving"). A question the student never
 * touched keeps whatever the server returned (its own prior answer, or
 * `null`), never reset to empty. */
export function seedAnswers(
  questions: readonly StudentQuizQuestion[],
): Record<string, { answerText: string | null; workingText: string | null }> {
  const out: Record<string, { answerText: string | null; workingText: string | null }> = {}
  for (const q of questions) {
    out[q.questionRef] = { answerText: q.answerText, workingText: q.workingText }
  }
  return out
}

// ── Local answer cache — survives a lost connection and a reload (UI spec
// S-04: "connection lost mid-test — answers must survive; resume after
// leaving"). Storage is injected (`Pick<Storage, "getItem" | "setItem">`,
// the `lemely/core/spaced_repetition.py` / chunk A precedent for injecting
// the ambient dependency rather than reaching for the global) so this is
// plain, unit-testable data logic — no DOM, no real `localStorage` — with
// the actual `window.localStorage` wired in only at the `QuizTaker.tsx`
// call site. ───────────────────────────────────────────────────────────

export type LocalAnswer = { answerText: string | null; workingText: string | null }

export interface CachedAnswerEntry extends LocalAnswer {
  /**
   * `true` while this entry reflects a local edit that has not yet been
   * confirmed saved to the server — the entry is strictly newer than
   * whatever the server has, and the merge below must not let a reload
   * throw it away in favour of the server's older value. Flipped to
   * `false` the moment the matching save succeeds; a `false` entry is
   * believed to equal the server, so a fresher server read (e.g. the take
   * payload after resuming on a different device) is allowed to win again.
   */
  dirty: boolean
}

export type CachedAnswers = Record<string, CachedAnswerEntry>

type ReadableStorage = Pick<Storage, "getItem">
type WritableStorage = Pick<Storage, "setItem">

export function answerCacheKey(assignmentId: string): string {
  return `lm.quiz.answers.${assignmentId}`
}

/** Read and parse the cached answers, or `null` for "nothing cached" —
 * covering both the genuinely-empty case (`getItem` returns `null`) and a
 * corrupt/unparseable value (manually edited storage, a schema change): a
 * bad cache degrades to "use the server value", it never throws and never
 * takes down the take screen. */
export function readCachedAnswers(storage: ReadableStorage, key: string): CachedAnswers | null {
  let raw: string | null
  try {
    raw = storage.getItem(key)
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
    return parsed as CachedAnswers
  } catch {
    return null
  }
}

/** Write the cache. Best-effort — a full/unavailable store (private
 * browsing) degrades resume-after-reload, not correctness, since the
 * in-memory state and the debounced server save are still the primary
 * paths. */
export function writeCachedAnswers(
  storage: WritableStorage,
  key: string,
  value: CachedAnswers,
): void {
  try {
    storage.setItem(key, JSON.stringify(value))
  } catch {
    // best-effort — see doc comment above.
  }
}

/**
 * Merge the server-seeded answers with whatever was cached locally. The
 * load-bearing rule: a local edit that failed to save before a reload must
 * not be silently discarded in favour of the server's older value.
 *
 * - No cache at all (`cached === null`) falls straight back to `server`
 *   (equivalently, `seedAnswers`'s own output) — nothing to merge.
 * - A cached entry still `dirty` (unsaved) wins over the server's value for
 *   that question — it is the newer one.
 * - A cached entry that is `dirty: false` (already confirmed saved, so
 *   believed equal to the server) does NOT override — the server's own
 *   value is treated as at least as fresh and wins, so a legitimate server
 *   update never loses to a stale, already-synced local copy.
 */
export function mergeAnswers(
  server: Record<string, LocalAnswer>,
  cached: CachedAnswers | null,
): Record<string, LocalAnswer> {
  if (!cached) return server
  const out: Record<string, LocalAnswer> = { ...server }
  for (const [questionRef, entry] of Object.entries(cached)) {
    if (!entry.dirty) continue
    out[questionRef] = { answerText: entry.answerText, workingText: entry.workingText }
  }
  return out
}

/** Which question refs still have an unsaved local edit — what the
 * retry-on-reconnect effect resends once the browser reports it's back
 * online. Pure decision over the cache; the `online` event listener itself
 * stays in `QuizTaker.tsx`. */
export function dirtyQuestionRefs(cached: CachedAnswers | null): string[] {
  if (!cached) return []
  return Object.entries(cached)
    .filter(([, entry]) => entry.dirty)
    .map(([questionRef]) => questionRef)
}

/**
 * Which refs the reconnect/reload retry should actually resend: still
 * dirty, and not already busy (a save on the wire, or one already chained
 * behind it — see `refsToFlush` and the queue notes below).
 *
 * The `busy` exclusion is load-bearing rather than tidy. An entry stays
 * `dirty: true` for the whole duration of its own save (it only flips on
 * success), so a retry pass that ran while a save was in flight would fire a
 * duplicate PUT for a question that is already on its way — and with a
 * second `online` transition or a re-run of the effect, several. The normal
 * debounced edit path deliberately does NOT consult this: a student who
 * types while a save is in flight must have that newer edit sent. It is not
 * dropped and it is not raced — it is chained behind the in-flight save and
 * reads the cache when its turn comes.
 */
export function refsToRetry(
  cached: CachedAnswers | null,
  busy: ReadonlySet<string>,
): string[] {
  return dirtyQuestionRefs(cached).filter((questionRef) => !busy.has(questionRef))
}

/**
 * Every ref a pre-submit flush must wait on before the paper may be
 * submitted: everything still dirty, PLUS everything currently busy.
 *
 * The second half is the part that is easy to get wrong. A question whose
 * save is on the wire right now is *not* safe to ignore just because a save
 * exists for it — that save may still fail, and a save that fails after
 * submit has already gone through marks the paper without an answer the
 * student can see on screen. Waiting on it means the post-flush
 * "is anything still dirty?" check sees its real outcome.
 *
 * Union, not concatenation: a ref that is both dirty and busy is one ref,
 * and enqueuing it twice would put a redundant PUT on the wire.
 */
export function refsToFlush(
  cached: CachedAnswers | null,
  busy: ReadonlySet<string>,
): string[] {
  return [...new Set([...dirtyQuestionRefs(cached), ...busy])]
}

/**
 * Is the cache still holding exactly what a completing save put on the
 * wire? Only then may that save mark the entry `dirty: false`.
 *
 * This is the guard against a fourth answer-loss path, distinct from the
 * three fixed in c2d444f. A save's completion handler used to write back the
 * value its own call had captured and mark it clean, unconditionally. But
 * two saves for one question could be in flight together (a reconnect retry
 * carrying the cached value, and a debounced edit carrying a just-typed
 * newer one), and network arrival order is not dispatch order, so the older
 * save could complete last — overwriting the newer answer in the cache and
 * stamping it "confirmed saved". The student keeps seeing their newer answer
 * on screen the whole time; on the next reload `mergeAnswers` sees
 * `dirty: false` and defers to the server, and the paper is marked against
 * the older text. Same confidently-wrong shape as D3.21, reached by a
 * different door.
 *
 * Per-question save chaining (`QuizTaker`'s `saveChains`) is the primary fix
 * — it means the two saves can no longer overlap at all, on the wire or at
 * the server, whose upsert is last-write-wins with no version guard. This
 * check is the second, independent line: it is value equality rather than
 * object identity on purpose, so a student who types a change and undoes it
 * back to the same text still gets a clean commit rather than a needless
 * resend.
 */
export function isCacheEntryUnchanged(
  cached: CachedAnswerEntry | undefined,
  sent: LocalAnswer,
): boolean {
  if (!cached) return false
  return cached.answerText === sent.answerText && cached.workingText === sent.workingText
}

/** The retry-on-reconnect save payload for one question: both fields,
 * explicitly, from the cache's own known-correct current values — not the
 * single-field payload `buildAnswerSavePayload` sends on a normal edit.
 * Safe specifically because a cache entry already holds the question's
 * true current state (seeded from the server, then only ever updated by a
 * real edit), so resending both fields re-asserts reality rather than
 * clobbering an untouched one with a stale `null`. */
export function buildRetrySavePayload(entry: LocalAnswer): SaveAnswerRequest {
  return { answerText: entry.answerText, workingText: entry.workingText }
}
