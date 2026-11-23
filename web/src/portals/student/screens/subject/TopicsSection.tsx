/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { TopicChips } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { TopicChipView } from "./subjectModel"
import "./subject.css"

/**
 * The kit reports a click as the text it drew, so the text it is given has to name one topic.
 * A short name shared by two topics (C1 Number, E1 Number) falls back to the full topic on each,
 * which also tells the two chips apart on screen. Routing then goes by that text back to the topic.
 */
function chipTexts(chips: TopicChipView[]): string[] {
  const topicsByLabel = new Map<string, Set<string>>()
  for (const c of chips) topicsByLabel.set(c.label, (topicsByLabel.get(c.label) ?? new Set()).add(c.topic))
  return chips.map((c) => ((topicsByLabel.get(c.label)?.size ?? 1) > 1 ? c.topic : c.label))
}

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
  const texts = chipTexts(chips)
  const topicByText = new Map(chips.map((c, i) => [texts[i], c.topic]))
  return (
    <section className="sj-sec" aria-labelledby="sj-topics-h">
      <SectionHeading id="sj-topics-h" title="Topics" />
      {chips.length > 0 ? (
        <TopicChips
          topics={chips.map((c, i) => ({ topic: texts[i], state: c.state, pct: c.pct }))}
          foldSecure={foldSecure}
          onSelect={(text) => onSelect(topicByText.get(text) ?? text)}
        />
      ) : null}
      {hint ? <p className="sj-hint">{hint}</p> : null}
    </section>
  )
}
