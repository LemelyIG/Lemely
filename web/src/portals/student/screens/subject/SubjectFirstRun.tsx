/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Camera, ChartBar, Sparkle } from "@phosphor-icons/react"
import { Walkthrough } from "@/components/redesign"
import { GhostSteps } from "./SubjectSteps"
import { TipSection } from "./TipSection"
import { FIRST_RUN_STEPS, GHOST_CHIPS, firstRunTip } from "./subjectModel"
import "./subject.css"

const ICONS = [Camera, Sparkle, ChartBar]

/** The live 404: no papers in this subject yet. */
export function SubjectFirstRun({ code, name, wide, twoCol }: { code: string; name: string; wide: boolean; twoCol: boolean }) {
  const steps = FIRST_RUN_STEPS(name).map((s, i) => ({ icon: ICONS[i], title: s.title, body: s.body }))
  return (
    <div className="sj-layout">
      <div className="sj-col">
        <section className="sj-sec" aria-labelledby="sj-path-h">
          <h2 id="sj-path-h" className="sj-h2">
            Your path to A*
          </h2>
          <GhostSteps />
        </section>
        <TipSection tip={firstRunTip(code, name)} size={wide ? 72 : twoCol ? 64 : 60} />
        <Walkthrough steps={steps} />
      </div>
      <div className="sj-col sj-col--aside-first-run">
        <section className="sj-sec" aria-labelledby="sj-topics-h">
          <h2 id="sj-topics-h" className="sj-h2">
            Topics
          </h2>
          <p className="sj-hint">Your strong and weak topics show up here after your first paper.</p>
          <div className="sj-ghostchips" aria-hidden="true">
            {GHOST_CHIPS.map((chip, i) => (
              <span key={i} className="sj-ghostchip" style={{ width: chip.width }} />
            ))}
          </div>
        </section>
        <section className="sj-sec" aria-labelledby="sj-papers-h">
          <h2 id="sj-papers-h" className="sj-h2">
            Papers
          </h2>
          <p className="sj-hint">Every {name} paper you mark lands here, newest first.</p>
        </section>
      </div>
    </div>
  )
}
