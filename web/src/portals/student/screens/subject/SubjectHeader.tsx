/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { CountdownPill } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import "./subject.css"

/**
 * The page's own heading row. The shell's top bar keeps the title and back
 * (shell wins); on native the h1 is visually hidden because the shell's large
 * title repeats it (`repeatsTitle`). The pill is the kit's linked variant, so
 * the chevron, the press, the focus ring and the 44px hit area come with it.
 */
export function SubjectHeader({
  title,
  subtitle,
  examDate,
  planTo,
  now,
}: {
  title: string
  subtitle: string
  examDate: string | null
  planTo: string
  now: Date
}) {
  return (
    <div className="sj-head">
      <div className="sj-head-t">
        <PageHeading repeatsTitle={true} className="sj-title">
          {title}
        </PageHeading>
        {subtitle ? <span className="sj-sub">{subtitle}</span> : null}
      </div>
      {examDate ? <CountdownPill examDate={examDate} now={now} subject={null} to={planTo} /> : null}
    </div>
  )
}
