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
  COUNT_DEFAULT, COUNT_MAX, COUNT_MIN, GENERATION_FAILED_TEXT, buildNewDeckRequest, clampCount,
  newDeckErrorMessage, newDeckOptions, newDeckOutcome, resolveMode, selectChip, selectKind, selectSubject,
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
      {["w-24", "w-32", "w-20"].map((w) => <SkeletonBlock key={w} className={`h-11 rounded-xl ${w}`} />)}
    </div>
  )
}

export function NewDeckSheet({ seed, onClose, onStarted }: {
  seed: NewDeckSeed | null; onClose: () => void; onStarted: (deckId: string) => void
}) {
  return seed ? <NewDeckForm seed={seed} onClose={onClose} onStarted={onStarted} /> : null
}

function NewDeckForm({ seed, onClose, onStarted }: {
  seed: NewDeckSeed; onClose: () => void; onStarted: (deckId: string) => void
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
    if (failedDeckId && !retryStarted.current && !retrying.has(failedDeckId)) discard.mutate(failedDeckId)
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
        const res = await generate.mutateAsync(req.body)
        const outcome = newDeckOutcome(res)
        if (outcome) toast(outcome)
        onStarted(res.deck.id)
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
            onClick={() => setSel(selectSubject(s.code))}
            className={`min-h-11 rounded-xl px-3 text-[13.5px] font-semibold ${FOCUS} ${s.code === subjectCode ? "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]"}`}>
            {s.name}
          </button>)}
        </div>
      ) : null}
      {!failedDeckId ? <>
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
              idle={overview.isPending ? <TopicsSkeleton /> : <p className="text-[14px] leading-[1.4] text-on-surface-variant">Pick a subject first</p>}
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
