/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
/* L4 · set builder sheet (mock PS, CB1-CB4). Replaces PracticeGenerator.tsx; every generator feature is on the keep-list. */
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { QueryState } from "@/components/ui/query-state"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useToast } from "@/components/ui/toast"
import { useCreatePractice, usePracticePreview, usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import type { PracticeFilterSet } from "@/lib/practiceTypes"
import { PrintIcon } from "../practiceIcons"
import { AvailabilityLine } from "./AvailabilityLine"
import {
  builderView,
  draftToFilters,
  editSession,
  newSession,
  seedSession,
  setSource,
  setWeakOnly,
  toggleBand,
  switchSubject,
  toggleTopic,
  visibleTopicGroups,
  weakServableTopics,
  type BuilderDraft,
  type CreateDestination,
} from "./builderModel"
import { CountStepper } from "./CountStepper"
import { MoreFilters } from "./MoreFilters"
import { runCreate } from "./runCreate"
import { SubjectChoice } from "./SubjectChoice"
import { TopicChips } from "./TopicChips"

/** `subjectCode: ""` disables `usePracticePreview` until a draft exists. */
const NO_FILTERS: PracticeFilterSet = { subjectCode: "", count: 0, topics: [], weakTopicsOnly: false, difficultyBands: [], source: null }
const GO = "min-h-[54px] w-full rounded-[18px] text-[16px] font-bold shadow-hover disabled:shadow-none"
/** The switch's label is a kit-owned span; this reaches it to match the mock's 14px semibold row. */
const WEAK_ROW = "min-h-11 justify-center [&_label_span]:!text-[14px] [&_label_span]:!font-[600] [&_label]:min-h-11 [&_label]:justify-center"
/** The kit's switch is 48x28; this grows its tap area to 44px high without moving it (9px past the padding box, since the 1px border sits outside it). */
const WEAK_SWITCH = "after:absolute after:inset-x-0 after:-inset-y-[9px] after:content-['']"

function TopicsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading topics" className="flex flex-wrap gap-1.5">
      {[96, 120, 84, 132, 104].map((w) => (
        <SkeletonBlock key={w} className="h-11 rounded-[12px]" style={{ width: w }} />
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
  const [session, setSession] = useState(() => newSession(initialSubject))
  // K11: seeding is a state update during render, which React replays safely; a ref write is not.
  const topicsQuery = usePracticeTopics(session.subjectCode)
  const seeded = seedSession(session, topicsQuery.data, initialSubject, focusTopic)
  if (seeded !== session) setSession(seeded)
  const { subjectCode, draft, dropped } = session
  const subjectName = allSubjects.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const filters = draft && draft.subjectCode === subjectCode ? draftToFilters(draft) : NO_FILTERS
  const previewQuery = usePracticePreview(filters)
  const create = useCreatePractice()

  const view = builderView({
    topicsStatus: topicsQuery.status,
    topics: topicsQuery.data,
    previewStatus: previewQuery.status,
    preview: previewQuery.data,
    race: session.race,
    creating: create.isPending,
    createFailed: session.createFailed,
    subjectName,
    otherSubjectNames: allSubjects.filter((s) => s.code !== subjectCode).map((s) => s.name),
    dropped,
  })

  // CB4: the banner appears after the busy button (and Print) unmounted, so keyboard focus would fall to the body.
  const ctaRef = useRef<HTMLButtonElement>(null)
  const failed = view.errorBanner !== null
  useEffect(() => {
    if (failed) ctaRef.current?.focus()
  }, [failed])

  const edit = (next: BuilderDraft) => setSession((s) => editSession(s, next))
  const chooseSubject = (code: string) => setSession((s) => switchSubject(s, code))

  async function make(dest: CreateDestination) {
    if (!draft || create.isPending) return
    await runCreate(
      {
        mutate: (f) => create.mutateAsync(f),
        update: setSession,
        invalidate: (queryKey) => void queryClient.invalidateQueries({ queryKey }),
        toast: (title) => toast({ title }),
        navigate: (to) => navigate(to, { replace: true }),
        refetchPreview: () => void previewQuery.refetch(),
      },
      draft,
      dest,
      view.startCount ?? draft.count,
    )
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
          <SubjectChoice subjects={allSubjects} value={subjectCode} onChange={chooseSubject} />

          {view.errorBanner ? (
            <div role="alert" className="rounded-[12px] bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container">
              {view.errorBanner}
            </div>
          ) : null}

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
                    className={WEAK_SWITCH}
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
            ref={ctaRef}
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
