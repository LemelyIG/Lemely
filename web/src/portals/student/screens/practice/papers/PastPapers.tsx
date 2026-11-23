/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* L4 · past papers (mock PP). Grouped by paper number, scores in Mono, a sheet to print. */
import { useState } from "react"
import { GhostRows, HairRow, HairRows } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { usePastPapers } from "@/lib/hooks/usePracticeHubApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import type { PastPaper } from "@/lib/practiceHubTypes"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
import { subjectFor } from "@/lib/reference"
import { SubjectChoice } from "../builder/SubjectChoice"
import { MonoNumbers } from "../hub/MonoNumbers"
import { usePracticeHubData } from "../hub/usePracticeHubData"
import { PaperIcon, TickIcon } from "../practiceIcons"
import { gatePapersQuery, noSubjectsCopy, resolvePapersSubject, subjectsGate } from "./papersFlow"
import { emptyPapersCopy, paperGroups } from "./papersModel"
import { PastPaperSheet } from "./PastPaperSheet"

const CENTRED_HEADING = "font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary"

export function PastPapers() {
  const hub = usePracticeHubData()
  const subjects = hub.builderSubjects
  const gate = subjectsGate({
    overviewStatus: hub.input.overviewStatus,
    profileStatus: hub.input.profileStatus,
    subjectCount: subjects.length,
  })
  const [chosen, setChosen] = useState<string | null>(null)
  const subject = resolvePapersSubject(subjects, chosen)
  const query = usePastPapers(subject.code)
  const { query: gated, refreshFailed } = gatePapersQuery(query)
  const [open, setOpen] = useState<PastPaper | null>(null)

  const { data: reference } = useReference()
  // The mock's "Cambridge IGCSE" line: the subject's own level, and nothing when it is unknown.
  const level = qualificationLevelLabel(reference?.qualificationLevels, subjectFor(reference, subject.code)?.qualificationLevel)
  const order = subjects.map((s) => s.code)
  const others = subjects.filter((s) => s.code !== subject.code).map((s) => s.name)

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-6 pb-6">
      <PageHeading repeatsTitle className="sr-only">
        Past papers
      </PageHeading>

      {gate === "loading" ? <GhostRows rows={4} withLeading /> : null}

      {gate === "error" ? (
        <ErrorState
          heading="We couldn’t load your subjects"
          body="Past papers are listed by subject. Check your connection and try again."
          action={{ label: "Try again", onClick: hub.refetchAll }}
        />
      ) : null}

      {gate === "none" ? (
        <div className="grid justify-items-center gap-2 py-6 text-center">
          <h2 className={CENTRED_HEADING}>{noSubjectsCopy().heading}</h2>
          <p className="max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">{noSubjectsCopy().body}</p>
        </div>
      ) : null}

      {gate === "ready" ? (
        <>
          {level ? <p className="-mb-3 text-[13px] font-medium text-on-surface-variant">{level}</p> : null}
          {subjects.length > 1 ? <SubjectChoice subjects={subjects} value={subject.code} onChange={setChosen} /> : null}

          <QueryState
            query={gated}
            skeleton={<GhostRows rows={4} withLeading />}
            error={{ heading: "We couldn’t load past papers" }}
            isEmpty={(data) => data.papers.length === 0}
            empty={
              <div className="grid justify-items-center gap-2 py-6 text-center">
                <h2 className={CENTRED_HEADING}>{emptyPapersCopy(subject.name, others).heading}</h2>
                <p className="max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">
                  {emptyPapersCopy(subject.name, others).body}
                </p>
              </div>
            }
          >
            {(data) => (
              <>
                {refreshFailed ? (
                  <ErrorState compact heading="Couldn’t refresh past papers" body="Showing your last loaded list.">
                    <Button variant="ghost" size="sm" className="min-h-11 self-start" loading={query.isFetching} onClick={() => void query.refetch()}>
                      Try again
                    </Button>
                  </ErrorState>
                ) : null}
                <div className="grid gap-6 lg:grid-cols-2 lg:items-start lg:gap-x-10">
                  {paperGroups(data.papers).map((group) => (
                    <section key={group.paperNumber} aria-label={group.heading} className="grid gap-1">
                      <h2 className="text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">{group.heading}</h2>
                      <HairRows aria-label={group.heading}>
                        {group.rows.map((row) => (
                          <HairRow
                            key={row.paperId}
                            leading={
                              <span
                                className={`grid size-10 place-items-center rounded-[13px] text-success-text ${row.done ? "bg-success-container" : "bg-success-container/70"}`}
                              >
                                {row.done ? <TickIcon /> : <PaperIcon size={20} />}
                              </span>
                            }
                            title={row.title}
                            sub={<MonoNumbers text={row.sub} />}
                            trailing={
                              row.score ? <span className="font-mono text-[14px] font-bold text-success-text">{row.score}</span> : undefined
                            }
                            onClick={() => setOpen(data.papers.find((p) => p.paperId === row.paperId) ?? null)}
                          />
                        ))}
                      </HairRows>
                    </section>
                  ))}
                </div>
              </>
            )}
          </QueryState>
        </>
      ) : null}

      {open ? <PastPaperSheet paper={open} subjectName={subject.name} subjectOrder={order} onClose={() => setOpen(null)} /> : null}
    </div>
  )
}
