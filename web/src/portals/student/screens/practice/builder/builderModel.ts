/*
 * Set builder sheet (L4) view model: the generator's decisions, moved out of
 * JSX. Pure; no `.tsx` imports. See the plan for the "Weak topics only"
 * semantics. The pressed chips are always exactly what is sent.
 */
import type {
  CreatePracticeResponse,
  PracticeFilterSet,
  PracticePreview,
  PracticeTopics,
} from "@/lib/practiceTypes"
import { plural, topicLabel, tryOthers } from "../practiceCopy"
import { groupTopicsBySyllabusGroup, practiceAvailabilityView, weakTopicPrefill, type TopicGroup } from "../practiceData"

export const COUNT_MIN = 5
export const COUNT_MAX = 30
export const COUNT_STEP = 5
export const COUNT_DEFAULT = 10

export interface BuilderDraft {
  subjectCode: string
  count: number
  weakOnly: boolean
  selected: string[]
  bands: string[]
  source: string | null
}

export interface DraftSeed {
  draft: BuilderDraft
  /** Weak topics with no chip on screen (K12). */
  dropped: string[]
}

export function stepCount(count: number, direction: 1 | -1): number {
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, count + direction * COUNT_STEP))
}

export function weakServableTopics(topics: PracticeTopics): string[] {
  return weakTopicPrefill(topics.weakTopics, topics.topics).selected
}

export function initialDraft(subjectCode: string, topics: PracticeTopics, focusTopic: string | null): DraftSeed {
  const prefill = weakTopicPrefill(topics.weakTopics, topics.topics)
  const base = { subjectCode, count: COUNT_DEFAULT, bands: [], source: null }
  if (focusTopic && topics.topics.some((t) => t.topic === focusTopic)) {
    return { draft: { ...base, weakOnly: false, selected: [focusTopic] }, dropped: prefill.dropped }
  }
  return {
    draft: { ...base, weakOnly: prefill.selected.length > 0, selected: prefill.selected },
    dropped: prefill.dropped,
  }
}

function toggle(list: readonly string[], item: string): string[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
}

export function toggleTopic(draft: BuilderDraft, topic: string): BuilderDraft {
  return { ...draft, selected: toggle(draft.selected, topic) }
}

export function toggleBand(draft: BuilderDraft, band: string): BuilderDraft {
  return { ...draft, bands: toggle(draft.bands, band) }
}

export function setWeakOnly(draft: BuilderDraft, on: boolean, weakServable: readonly string[]): BuilderDraft {
  if (!on) return { ...draft, weakOnly: false }
  return { ...draft, weakOnly: true, selected: draft.selected.filter((t) => weakServable.includes(t)) }
}

export function setSource(draft: BuilderDraft, source: string | null): BuilderDraft {
  return { ...draft, source }
}

export function draftToFilters(draft: BuilderDraft): PracticeFilterSet {
  const serverWeak = draft.weakOnly && draft.selected.length === 0
  return {
    subjectCode: draft.subjectCode,
    count: draft.count,
    topics: serverWeak ? [] : [...draft.selected],
    weakTopicsOnly: serverWeak,
    difficultyBands: [...draft.bands],
    source: draft.source,
  }
}

export function visibleTopicGroups(topics: PracticeTopics, weakOnly: boolean): TopicGroup[] {
  if (!weakOnly) return groupTopicsBySyllabusGroup(topics.topics)
  const weak = new Set(weakServableTopics(topics))
  return groupTopicsBySyllabusGroup(topics.topics.filter((t) => weak.has(t.topic)))
}

export type BuilderBody = "loading" | "topicsError" | "noQuestions" | "ready"
export type LineTone = "wait" | "ok" | "short" | "none" | "error"
export interface AvailabilityLine {
  tone: LineTone
  text: string
}

export interface BuilderViewInput {
  topicsStatus: "pending" | "error" | "success"
  topics: PracticeTopics | undefined
  previewStatus: "pending" | "error" | "success"
  preview: PracticePreview | undefined
  /** The 409 payload from create, which overrides the preview until a filter changes. */
  race: PracticePreview | null
  creating: boolean
  createFailed: boolean
  subjectName: string
  otherSubjectNames: readonly string[]
  dropped: readonly string[]
}

export interface BuilderView {
  body: BuilderBody
  noQuestions: { heading: string; body: string } | null
  line: AvailabilityLine | null
  cta: { label: string; disabled: boolean }
  showPrint: boolean
  errorBanner: string | null
  droppedNote: string | null
  untopicedNote: string | null
  /** The size the created set should have, for `createdToast`. */
  startCount: number | null
}

export function unavailableText(reason: string | null): string {
  switch (reason) {
    case "no_weaknesses":
      return "No weak topics yet. Turn this off to pick any topic."
    case "no_questions":
      return "Nothing matches. Try other topics or another difficulty."
    default:
      return reason ? `Not available right now (${reason}).` : "Not available right now."
  }
}

function matchText(n: number): string {
  return `${plural(n, "question")} ${n === 1 ? "matches" : "match"}`
}

function droppedNote(dropped: readonly string[]): string | null {
  if (dropped.length === 0) return null
  if (dropped.length === 1) return `${topicLabel(dropped[0])} isn't in the question bank yet.`
  return `${dropped.length} weak topics aren't in the question bank yet: ${dropped.map(topicLabel).join(", ")}.`
}

function untopicedNote(n: number): string | null {
  return n > 0 ? `Plus ${plural(n, "untagged question")}, used when no topic is picked.` : null
}

const START = "Start now"

export function builderView(i: BuilderViewInput): BuilderView {
  const idle: BuilderView = {
    body: "loading",
    noQuestions: null,
    line: null,
    cta: { label: START, disabled: true },
    showPrint: false,
    errorBanner: null,
    droppedNote: droppedNote(i.dropped),
    untopicedNote: null,
    startCount: null,
  }
  if (i.topicsStatus === "pending") return idle
  if (i.topicsStatus === "error" || !i.topics) return { ...idle, body: "topicsError" }
  if (i.topics.topics.length === 0 && i.topics.untopicedCount === 0) {
    return {
      ...idle,
      body: "noQuestions",
      droppedNote: null,
      noQuestions: { heading: `No ${i.subjectName} questions yet`, body: tryOthers(i.otherSubjectNames) },
    }
  }

  const effective = i.race ?? (i.previewStatus === "success" ? (i.preview ?? null) : null)
  let line: AvailabilityLine
  let label = START
  let enabled = false
  let startCount: number | null = null
  if (effective) {
    const view = practiceAvailabilityView(effective)
    if (view.kind === "unavailable") {
      line = { tone: "none", text: unavailableText(view.reason) }
    } else if (view.kind === "shortfall") {
      line = { tone: "short", text: `Only ${matchText(view.availableCount)}. Add a topic or ask for fewer.` }
      label = `Start with ${view.availableCount}`
      enabled = true
      startCount = view.availableCount
    } else {
      line = { tone: "ok", text: matchText(view.availableCount) }
      enabled = true
      startCount = view.requestedCount
    }
  } else if (i.previewStatus === "error") {
    line = { tone: "error", text: "Couldn't check what matches. Change a filter to try again." }
  } else {
    line = { tone: "wait", text: "Checking what matches…" }
  }

  const ready: BuilderView = {
    ...idle,
    body: "ready",
    line,
    untopicedNote: untopicedNote(i.topics.untopicedCount),
    startCount,
    cta: { label, disabled: !enabled },
    showPrint: enabled,
  }
  if (i.creating) return { ...ready, cta: { label: "Making your set…", disabled: true }, showPrint: false }
  if (i.createFailed && !i.race && enabled) {
    return { ...ready, errorBanner: "Couldn't make this set. Try again.", cta: { label: "Try again", disabled: false } }
  }
  return ready
}

export function createdToast(created: CreatePracticeResponse, expected: number): string | null {
  return created.questionCount < expected ? `Made a set of ${created.questionCount}. That's all that matched.` : null
}
