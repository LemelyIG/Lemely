/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { TopicChips } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { TopicChipView } from "./subjectModel"
import "./subject.css"

/**
 * The kit's `TopicChips` draws its own three-state legend under the chips, so this
 * section adds none: a second legend would only repeat the first.
 */
export function TopicsSection({
  chips,
  foldSecure,
  hint,
  onSelect,
}: {
  chips: TopicChipView[]
  foldSecure: boolean
  hint: string | null
  onSelect: (topic: string) => void
}) {
  const byLabel = new Map<string, string>()
  for (const c of chips) if (!byLabel.has(c.label)) byLabel.set(c.label, c.topic)
  return (
    <section className="sj-sec" aria-labelledby="sj-topics-h">
      <SectionHeading id="sj-topics-h" title="Topics" />
      {chips.length > 0 ? (
        <TopicChips
          topics={chips.map((c) => ({ topic: c.label, state: c.state, pct: c.pct }))}
          foldSecure={foldSecure}
          onSelect={(label) => onSelect(byLabel.get(label) ?? label)}
        />
      ) : null}
      {hint ? <p className="sj-hint">{hint}</p> : null}
    </section>
  )
}
