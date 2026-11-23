/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import { useRef, useState } from "react"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"
import { usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { useCreateDeck, useDeleteDeck, useGenerateDeck, useRetryGeneration, useRetryingDeckIds, useWeakTopics } from "@/lib/hooks/useFlashcardApi"
import { CountStepper } from "./parts/CountStepper"
import { FcSheet } from "./parts/FcSheet"
import {
  COUNT_DEFAULT, COUNT_MAX, COUNT_MIN, GENERATION_FAILED_TEXT, buildNewDeckRequest, clampCount, failedDeckToDiscard, finishGeneration,
  newDeckErrorMessage, newDeckOptions, resolveMode, selectChip, selectKind, selectSubject,
  submitLabel, topicChips, weaknessChips, type DeckSelection, type NewDeckMode,
} from "./newDeckView"

export interface NewDeckSeed {
  mode: NewDeckMode | null
  subjectCode: string
  topic: string | null
  failedDeckId?: string
}

const ICONS = { weakness: Target, topic: Sparkle, manual: PencilSimple } as const
const TONES = {
  weakness: "bg-error-container text-on-error-container",
  topic: "bg-secondary-container text-on-secondary-container",
  manual: "bg-primary-container text-primary",
} as const
const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

/** Three chip-shaped blocks, so the topics keep their place while they load. */
function TopicsSkeleton() {
  return (
    <div className="flex flex-wrap gap-1.5" role="status" aria-label="Loading topics">
      {["w-24", "w-32", "w-20"].map((w) => <SkeletonBlock key={w} announce={false} className={`h-11 rounded-xl ${w}`} />)}
    </div>
  )
}

/**
 * With no subject in hand every kind of deck is a dead end, so the form gives way to the reason:
 * the subjects are still loading, could not load, or the student has none yet.
 */
function NoSubjects({ overview }: { overview: ReturnType<typeof useOverview> }) {
  return (
    <QueryState
      query={overview}
      skeleton={<div className="grid gap-2" role="status" aria-label="Loading subjects">
        {[0, 1, 2].map((i) => <SkeletonBlock key={i} announce={false} className="h-[60px] rounded-2xl" />)}
      </div>}
      error={{ heading: "Couldn’t load your subjects", retryLabel: "Try again", compact: true }}
      isEmpty={(data) => data.subjects.length === 0}
      empty={<p className="text-[14px] leading-[1.4] text-on-surface-variant">No subjects yet.</p>}
    >
      {() => null}
    </QueryState>
  )
}

export function NewDeckSheet({ seed, onClose, onStarted, onDiscarded }: {
  seed: NewDeckSeed | null
  onClose: () => void
  onStarted: (deckId: string) => void
  /** A failed deck was deleted because its sheet closed without a retry. */
  onDiscarded?: (deckId: string) => void
}) {
  return seed ? <NewDeckForm seed={seed} onClose={onClose} onStarted={onStarted} onDiscarded={onDiscarded} /> : null
}

function NewDeckForm({ seed, onClose, onStarted, onDiscarded }: {
  seed: NewDeckSeed; onClose: () => void; onStarted: (deckId: string) => void; onDiscarded?: (deckId: string) => void
}) {
  const overview = useOverview()
  const subjects = overview.data?.subjects ?? []
  const [sel, setSel] = useState<DeckSelection>({ subject: seed.subjectCode, chosenMode: seed.mode, topic: seed.topic })
  const { topic } = sel
  const subjectCode = sel.subject || subjects[0]?.code || ""
  const [count, setCount] = useState(COUNT_DEFAULT)
  const [title, setTitle] = useState("")
  const weak = useWeakTopics()
  const topics = usePracticeTopics(subjectCode)
  const create = useCreateDeck()
  const generate = useGenerateDeck()
  const discard = useDeleteDeck()
  const { toast } = useToast()
  const retry = useRetryGeneration(() => toast({ variant: "error", title: "Couldn’t retry that deck", description: "Try again in a moment." }))
  const retrying = useRetryingDeckIds()
  const retryStarted = useRef(false)
  const options = newDeckOptions(weak.data ?? [], subjectCode)
  const mode = resolveMode(sel.chosenMode, options)
  const subjectName = subjects.find((s) => s.code === subjectCode)?.name ?? subjectCode
  const chips = mode === "weakness" ? weaknessChips(weak.data ?? [], subjectCode)
    : mode === "topic" ? topicChips((topics.data?.topics ?? []).map((t) => t.topic)) : []
  const req = buildNewDeckRequest({ mode, subjectCode, subjectName, topic, count, title,
    weakTopics: weaknessChips(weak.data ?? [], subjectCode).map((chip) => chip.topic) })
  const pending = create.isPending || generate.isPending
  // ApiError carries `status` and `detail`; newDeckErrorMessage reads them structurally.
  const requestError = (create.error ?? generate.error) as { status?: number; detail?: unknown } | null
  const failedDeckId = seed.failedDeckId
  const chipGroup = (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Topic">
      {chips.map((c) => <button key={c.topic} type="button" aria-pressed={c.topic === topic}
        onClick={() => setSel((s) => selectChip(s, mode, c.topic))}
        className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-[13.5px] font-semibold ${FOCUS} ${mode === "weakness" ? "bg-error-container text-on-error-container" : "bg-surface-container-low text-on-surface"} ${c.topic === topic ? mode === "weakness" ? "shadow-[inset_0_0_0_2px_var(--color-on-error-container)]" : "shadow-[inset_0_0_0_2px_var(--color-primary)]" : ""}`}>
        <span>{c.label}</span>{c.badge ? <b className="font-mono text-xs">{c.badge}</b> : null}
      </button>)}
    </div>
  )

  function close() {
    if (pending) return
    const discardId = failedDeckToDiscard({
      failedDeckId, retryStarted: retryStarted.current, retrying: !!failedDeckId && retrying.has(failedDeckId),
    })
    // The promise, not `mutate`'s callback: `onClose` unmounts this form, and a callback passed to
    // `mutate` does not fire once its component is gone. The screen behind it must hear the deck left.
    if (discardId) void discard.mutateAsync(discardId).then(() => onDiscarded?.(discardId), () => {})
    onClose()
  }

  async function submit() {
    if (failedDeckId) {
      retryStarted.current = true
      retry.mutate(failedDeckId)
      onClose()
      return
    }
    try {
      if (req.kind === "generate") {
        finishGeneration(await generate.mutateAsync(req.body), toast, onStarted)
      } else if (req.kind === "create") onStarted((await create.mutateAsync(req.body)).id)
    } catch {
      // Mutation errors are rendered below the form.
    }
  }

  return (
    <FcSheet open onOpenChange={(open) => { if (!open) close() }} title="New deck">
      {failedDeckId ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{GENERATION_FAILED_TEXT}</div> : null}
      {!failedDeckId && subjects.length > 1 ? (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Subject">
          {subjects.map((s) => <button key={s.code} type="button" aria-pressed={s.code === subjectCode}
            onClick={() => setSel((cur) => selectSubject(cur, s.code, subjectCode))}
            className={`min-h-11 rounded-xl px-3 text-[13.5px] font-semibold ${FOCUS} ${s.code === subjectCode ? "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]"}`}>
            {s.name}
          </button>)}
        </div>
      ) : null}
      {!failedDeckId && !subjectCode ? <NoSubjects overview={overview} /> : null}
      {!failedDeckId && subjectCode ? <>
        <div className="grid gap-2" role="radiogroup" aria-label="Kind of deck">
          {options.map((o) => {
            const Icon = ICONS[o.mode]
            const selected = o.mode === mode
            return <button key={o.mode} type="button" role="radio" aria-checked={selected} disabled={o.disabled}
              onClick={() => setSel((s) => selectKind(s, o.mode))}
              className={`grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)] items-center gap-3 rounded-2xl px-3 py-2.5 text-start text-on-surface disabled:opacity-60 ${FOCUS} ${selected ? "bg-primary-container shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]"}`}>
              <span className={`grid size-10 place-items-center rounded-xl ${TONES[o.mode]}`}><Icon size={14} weight="bold" aria-hidden /></span>
              <span className="grid"><b className="text-[15px] font-bold">{o.title}</b><span className="text-[13px] text-on-surface-variant">{o.sub}</span></span>
            </button>
          })}
        </div>
        {mode === "manual" ? (
          <label className="grid gap-1.5 text-[13px] font-semibold text-on-surface-variant">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${subjectName} deck`}
              className={`rounded-2xl bg-surface-container-lowest px-3.5 py-3 text-[16px] text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] ${FOCUS}`} />
          </label>
        ) : <>
          {mode === "topic" ? (
            <QueryState
              query={topics}
              skeleton={<TopicsSkeleton />}
              error={{ heading: "Couldn’t load topics", retryLabel: "Try again", compact: true }}
              isEmpty={(data) => data.topics.length === 0}
              empty={<p className="text-[14px] leading-[1.4] text-on-surface-variant">No topics for this subject yet.</p>}
            >
              {() => chipGroup}
            </QueryState>
          ) : chipGroup}
          <CountStepper label="Cards" value={count} min={COUNT_MIN} max={COUNT_MAX} onChange={(n) => setCount(clampCount(n))} />
        </>}
      </> : null}
      {requestError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{newDeckErrorMessage(requestError)}</div> : null}
      <button type="button" onClick={() => void submit()} disabled={pending || (!failedDeckId && (!subjectCode || req.kind === "invalid")) || (!!failedDeckId && retrying.has(failedDeckId))}
        className={`min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary disabled:bg-surface-container-high disabled:text-on-surface-variant ${FOCUS}`}>
        {failedDeckId ? "Try again" : submitLabel(mode, count, pending)}
      </button>
    </FcSheet>
  )
}
