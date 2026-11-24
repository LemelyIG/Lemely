/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { PathSection } from "./PathSection"
import { PapersList } from "./PapersList"
import { TipSection } from "./TipSection"
import { TopicsSection } from "./TopicsSection"
import { WinList } from "./WinList"
import { links, visiblePapers, type SubjectView } from "./subjectModel"
import "./subject.css"

/** Full and sparse. One column on phone; from 768px left = path, tip, win and right = topics, papers. */
export function SubjectBody({
  view,
  code,
  wide,
  twoCol,
  onSelectPaper,
}: {
  view: SubjectView
  code: string
  wide: boolean
  twoCol: boolean
  onSelectPaper: (n: number) => void
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="sj-layout">
      <div className="sj-col">
        <PathSection path={view.path} onSelect={onSelectPaper} />
        <TipSection tip={view.tip} size={wide ? 72 : twoCol ? 64 : 60} />
        {view.win.rows.length > 0 ? <WinList win={view.win} allTo={links.practice(code)} /> : null}
      </div>
      <div className="sj-col">
        <TopicsSection
          chips={view.chips}
          foldSecure={view.mode === "full" && !wide}
          hint={view.topicsHint}
          allTo={links.practice(code)}
          onSelect={(topic) => navigate(links.practice(code, topic))}
        />
        <PapersList rows={view.papers} visible={visiblePapers(view.papers.length, wide, expanded)} onShowAll={() => setExpanded(true)} />
      </div>
    </div>
  )
}
