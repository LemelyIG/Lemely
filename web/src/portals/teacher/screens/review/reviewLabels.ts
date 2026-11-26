import { confidenceTierFor, markerScored } from "@/lib/markingConfidence"
import type { ReviewQueueItem } from "@/lib/teacherTypes"

export const REASON_LABEL: Record<string, string> = {
  low_confidence: "Low confidence",
  // F4: renamed from "Possible mark-scheme copying" — the check is a
  // similarity match against the mark scheme's own model answer, and this
  // label says exactly that rather than implying a judgement about intent.
  plagiarism_flag: "Matches mark-scheme wording",
  manual: "Manually flagged",
  random_audit: "Random audit",
  student_evidence_unjudged: "Student challenged a mark",
  // `ai_detection_flag` is deliberately absent: F4 removed the detector and
  // `0037_remove_ai_detection` rewrote every row carrying that reason to
  // `manual`, so no queue row can reach this map with it. `reasonLabel` falls
  // back to the raw value, which is what `reviewAdvisoryCopy.test.ts` pins.
}

export function reasonLabel(reason: string): string {
  return REASON_LABEL[reason] ?? reason
}

export const INTEGRITY_REASONS = new Set(["plagiarism_flag"])

export function isIntegrityReason(reason: string): boolean {
  return INTEGRITY_REASONS.has(reason)
}

/**
 * Whether a row came from the grading console rather than a student submission.
 *
 * Branch on `source`, never on "is `studentId` null" — the queue holds two
 * kinds of row (migration `0034`) and the backend says which explicitly so the
 * client never has to infer it from which ids happen to be populated.
 *
 * A `console_paper` row is a scan the teacher uploaded themselves. It has no
 * student and no class behind it (D1.12), so the student/class fields are
 * `null` and there is nowhere to link to for either; the paper's own label —
 * the same one its grading-console card carries — is its identity instead.
 */
export function isConsolePaperItem(item: { source: string }): boolean {
  return item.source === "console_paper"
}

/** Honest paper-identity line. A review item can originate from a quiz
 * question (P3.5's low-confidence quiz marking path also queues review
 * items) whose `Attempt` carries no subject/paper/session fields at all —
 * render "Quiz question" rather than a blank or half-filled identity line. */
export function paperIdentityLabel(item: {
  subjectCode: string | null
  paperNumber: number | null
  paperVariant: number | null
  sessionMonth: string | null
  sessionYear: number | null
}): string {
  if (!item.subjectCode) return "Quiz question"
  const parts = [item.subjectCode]
  if (item.paperNumber != null) {
    parts.push(`Paper ${item.paperNumber}${item.paperVariant != null ? `/${item.paperVariant}` : ""}`)
  }
  if (item.sessionMonth && item.sessionYear) {
    parts.push(`${item.sessionMonth} ${item.sessionYear}`)
  }
  return parts.join(" · ")
}

/**
 * Colour-coded confidence tone. The number itself is always rendered too
 * (QUALITY-BAR: colour is never the sole carrier of meaning), so this only
 * picks which semantic token tints the chip.
 *
 * **P4.5: this bucketed at 0.8, on the one screen where that is worst.** The
 * review queue exists *because* a mark scored below
 * `REVIEW_CONFIDENCE_THRESHOLD` (0.90) — that is what put it here. Painting
 * anything at or above 0.8 with the `ok` token meant a mark at 0.85 arrived in
 * the queue as not-confident and was then shown to the teacher in the same
 * green the product uses for "we are sure about this one". A teacher scanning
 * the queue for what actually needs their judgement was being pointed away
 * from items the marker had already said it was unsure about.
 *
 * This is D4.2's finding a second time. There it was the student's paper
 * result at 0.85 against the backend's 0.90; `lib/markingConfidence.ts` was
 * built to be the single owner of this decision precisely so it could not
 * happen again, and this file is now a caller rather than a second authority.
 *
 * **It also drops from three tones to two, and that is the point rather than
 * a casualty.** The old third band split "uncertain" again at 0.5, and there
 * is no such number anywhere in the product: the backend has exactly one
 * confidence threshold, so any second boundary is a frontend invention, which
 * is the defect class this whole module exists to close. Two tones is what the
 * data actually supports. Nothing is lost to the reader, because the score
 * itself is always printed beside the chip: a teacher can still tell 30% from
 * 85%, they simply are not told that the product considers one of them a
 * different *kind* of doubt when it has no basis for saying so.
 *
 * `null` stays its own case: a queue item with no score at all, which the
 * integrity checks produce, is genuinely not the same as a low score.
 *
 * US-039 finding G. `markerSource` is optional and — for this queue's own
 * row type, `ReviewQueueItemDTO` — always absent: it isn't on that DTO's
 * wire shape at all today, only on `ReviewItemDetailDTO`'s (T-08's single-item
 * view).
 *
 * **A genuine blank cannot reach this queue as a `plagiarism_flag` row at
 * all.** `integrity.py` is the only writer of `plagiarism_flagged` and its
 * gate requires `expected_answer` truthy; every site that sets
 * `expected_answer` non-`None` also sets `marker_source="deterministic"`. No
 * unscored marker source can therefore ever be `plagiarism_flagged`, so this
 * parameter's neutral-tone branch cannot fire on any row this queue holds
 * today. It is added anyway, as a defensive gate rather than a live one:
 * `ReviewQueueItemDTO` doesn't carry `markerSource` at all today, but if a
 * future producer ever emits an unscored row into this queue, this function
 * already knows what to do with it.
 *
 * This asks `markerScored` rather than going through `confidenceTierFor`'s
 * `needsTeacherReview`-gated "not-marked" branch: this screen has no
 * `reviewReason`/`needsTeacherReview` to give that function (it never did —
 * see the two-tones note above), so requiring them would make the gate
 * exactly as unreachable as the bug this closes. An unscored marker source is
 * unambiguous on its own: no marker (human or AI) produced this score, so it
 * cannot be a confidence tone at all. Task #36 replaced a hand-spelled
 * `=== "missing" || === "dropped"` here with the shared predicate — that
 * spelling would have silently excluded `"blank"`.
 */
export function confidenceTone(
  score: number | null,
  markerSource?: string | null,
): "ok" | "warn" | "neutral" {
  if (score == null) return "warn"
  if (!markerScored(markerSource)) return "neutral"
  return confidenceTierFor({ confidence: score }) === "confident" ? "ok" : "warn"
}

export const REASON_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All reasons" },
  { value: "low_confidence", label: "Low confidence" },
  // F4's wording, not develop's "Possible mark-scheme copying" — see
  // `REASON_LABEL` above for why the label does not imply intent.
  { value: "plagiarism_flag", label: "Matches mark-scheme wording" },
  { value: "student_evidence_unjudged", label: "Student challenged a mark" },
]

export const AGE_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any age" },
  { value: "6", label: "6+ hours" },
  { value: "24", label: "24+ hours" },
  { value: "72", label: "3+ days" },
  { value: "168", label: "7+ days" },
]

export const SKIP_REASON_LABEL: Record<string, string> = {
  not_found: "no longer exists",
  forbidden: "outside your classes",
  already_closed: "already resolved or dismissed",
}

/**
 * Task 11 (B6c) — accumulates review-queue pages across "Load more" clicks.
 *
 * `page.key` is the current filter tuple (`classId|reason|minAgeHours`):
 * when it differs from `prev.key`, a filter changed underneath the
 * accumulated list, so the new page **replaces** it outright rather than
 * appending onto rows the current filters no longer select. When the key
 * matches, `page.items` is the next cursor's page and gets **appended**,
 * deduped by `itemId` — a background refetch of the first page (react-query
 * revalidating on window focus, say) can redeliver rows already present in
 * a later page's accumulated list, and a duplicate `key` in the table's
 * `.map()` below is a React error, not just a cosmetic double row.
 */
export function mergeReviewPages(
  prev: { key: string; items: ReviewQueueItem[] },
  page: { key: string; items: ReviewQueueItem[] },
): { key: string; items: ReviewQueueItem[] } {
  if (prev.key !== page.key) return page
  const seen = new Set(prev.items.map((item) => item.itemId))
  return { key: page.key, items: [...prev.items, ...page.items.filter((item) => !seen.has(item.itemId))] }
}
