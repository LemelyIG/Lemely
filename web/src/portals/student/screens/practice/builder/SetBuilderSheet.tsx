/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
/* L4 · set builder sheet (mock PS, CB1-CB4). Replaces PracticeGenerator.tsx; every generator feature is on the keep-list. */
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { practiceHubKeys } from "@/lib/practiceHubKeys"
import { useCreatePractice, usePracticePreview, usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import type { PracticeFilterSet, PracticePreview } from "@/lib/practiceTypes"
import { PrintIcon } from "../practiceIcons"
import { AvailabilityLine } from "./AvailabilityLine"
import {
  builderView,
  createdToast,
  draftToFilters,
  initialDraft,
  setSource,
  setWeakOnly,
  toggleBand,
  toggleTopic,
  visibleTopicGroups,
  weakServableTopics,
  type BuilderDraft,
} from "./builderModel"
import { CountStepper } from "./CountStepper"
import { MoreFilters } from "./MoreFilters"
import { SubjectChoice } from "./SubjectChoice"
import { TopicChips } from "./TopicChips"

/** `subjectCode: ""` disables `usePracticePreview` until a draft exists. */
const NO_FILTERS: PracticeFilterSet = { subjectCode: "", count: 0, topics: [], weakTopicsOnly: false, difficultyBands: [], source: null }
const GO = "min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-hover disabled:shadow-none"
/** The switch's label is a kit-owned span; this reaches it to match the mock's 14px semibold row. */
const WEAK_ROW = "min-h-11 justify-center [&_label_span]:text-[14px] [&_label_span]:font-semibold"

function TopicsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading topics" className="flex flex-wrap gap-1.5">
      {[96, 120, 84, 132, 104].map((w) => (
        <SkeletonBlock key={w} className="h-11 rounded-xl" style={{ width: w }} />
      ))}
    </div>
  )
}

export function SetBuilderSheet({
  subjects,
  initialSubject,
  focusTopic,
  onClose,
}: {
  subjects: { code: string; name: string }[]
  initialSubject: string
  focusTopic: string | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { data: reference } = useReference()

  // A deep link can name a subject the student is not enrolled in; it still gets a chip.
  const allSubjects = subjects.some((s) => s.code === initialSubject)
    ? subjects
    : [{ code: initialSubject, name: initialSubject }, ...subjects]
  const [subjectCode, setSubjectCode] = useState(initialSubject)
  const subjectName = allSubjects.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const topicsQuery = usePracticeTopics(subjectCode)
  const [draft, setDraft] = useState<BuilderDraft | null>(null)
  const [dropped, setDropped] = useState<string[]>([])
  // K11: prefill once per subject, the moment its topics arrive; a refetch never reverts a choice.
  // State, not a ref: an update during render is replayed safely, a ref write is not.
  const [seededFor, setSeededFor] = useState<string | null>(null)
  if (topicsQuery.data && seededFor !== subjectCode) {
    const seed = initialDraft(subjectCode, topicsQuery.data, subjectCode === initialSubject ? focusTopic : null)
    setSeededFor(subjectCode)
    setDraft(seed.draft)
    setDropped(seed.dropped)
  }

  const filters = draft && draft.subjectCode === subjectCode ? draftToFilters(draft) : NO_FILTERS
  const previewQuery = usePracticePreview(filters)
  const create = useCreatePractice()
  const [race, setRace] = useState<PracticePreview | null>(null)
  const [createFailed, setCreateFailed] = useState(false)

  const view = builderView({
    topicsStatus: topicsQuery.status,
    topics: topicsQuery.data,
    previewStatus: previewQuery.status,
    preview: previewQuery.data,
    race,
    creating: create.isPending,
    createFailed,
    subjectName,
    otherSubjectNames: allSubjects.filter((s) => s.code !== subjectCode).map((s) => s.name),
    dropped,
  })

  function edit(next: BuilderDraft) {
    setRace(null)
    setCreateFailed(false)
    setDraft(next)
  }

  function chooseSubject(code: string) {
    if (code === subjectCode) return
    setRace(null)
    setCreateFailed(false)
    setDraft(null)
    setDropped([])
    // Clearing this too lets a return trip to an already-seeded subject seed again.
    setSeededFor(null)
    setSubjectCode(code)
  }

  async function make(dest: "set" | "print") {
    if (!draft) return
    setRace(null)
    setCreateFailed(false)
    try {
      const created = await create.mutateAsync(draftToFilters(draft))
      void queryClient.invalidateQueries({ queryKey: practiceHubKeys.runsAll })
      const note = createdToast(created, view.startCount ?? draft.count)
      if (note) toast({ title: note })
      navigate(
        dest === "set" ? `/student/practice/set/${created.assignmentId}` : `/student/practice/print/${created.assignmentId}`,
        { replace: true },
      )
    } catch (err) {
      // K22: a 409 carries the preview payload; show that refusal, not a generic failure.
      if (err instanceof ApiError && err.status === 409 && err.detail) {
        setRace(err.detail as PracticePreview)
      } else {
        setCreateFailed(true)
        void previewQuery.refetch()
      }
    }
  }

  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent
        side="adaptive"
        aria-describedby={undefined}
        nativeHeader={<SheetTitle className="text-[22px] font-extrabold text-on-surface">Practice set</SheetTitle>}
        nativeBodyClassName="grid gap-3 px-5 pt-1 pb-6"
      >
        <div className="grid gap-3">
          {view.errorBanner ? (
            <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container">
              {view.errorBanner}
            </div>
          ) : null}

          <SubjectChoice subjects={allSubjects} value={subjectCode} onChange={chooseSubject} />

          <QueryState
            query={topicsQuery}
            skeleton={<TopicsSkeleton />}
            error={{ heading: "Couldn’t load topics", compact: true }}
          >
            {(topics) =>
              view.body === "noQuestions" && view.noQuestions ? (
                <div className="grid justify-items-center gap-2 py-2 text-center">
                  <h3 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
                    {view.noQuestions.heading}
                  </h3>
                  <p className="max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">{view.noQuestions.body}</p>
                </div>
              ) : draft ? (
                <div className="grid gap-3">
                  <Switch
                    layout="row"
                    label="Weak topics only"
                    checked={draft.weakOnly}
                    onCheckedChange={(on) => edit(setWeakOnly(draft, on, weakServableTopics(topics)))}
                    wrapperClassName={WEAK_ROW}
                  />
                  <TopicChips
                    groups={visibleTopicGroups(topics, draft.weakOnly)}
                    selected={draft.selected}
                    onToggle={(topic) => edit(toggleTopic(draft, topic))}
                  />
                  {view.droppedNote ? <p className="text-[12.5px] text-on-surface-variant">{view.droppedNote}</p> : null}
                  {view.untopicedNote ? <p className="text-[12.5px] text-on-surface-variant">{view.untopicedNote}</p> : null}
                  <CountStepper value={draft.count} onChange={(count) => edit({ ...draft, count })} />
                  <MoreFilters
                    bands={draft.bands}
                    availableBands={reference?.difficultyBands ?? []}
                    source={draft.source}
                    onToggleBand={(band) => edit(toggleBand(draft, band))}
                    onSource={(source) => edit(setSource(draft, source))}
                  />
                  {view.line ? <AvailabilityLine line={view.line} /> : null}
                </div>
              ) : null
            }
          </QueryState>

          <Button
            variant="primary"
            size="lg"
            className={GO}
            disabled={view.cta.disabled}
            loading={create.isPending}
            onClick={() => void make("set")}
          >
            {view.cta.label}
          </Button>
          {view.showPrint ? (
            <button
              type="button"
              className="inline-flex min-h-11 items-center justify-center gap-1.5 text-[14px] font-semibold text-on-surface-variant focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
              onClick={() => void make("print")}
            >
              <PrintIcon /> Print instead
            </button>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
