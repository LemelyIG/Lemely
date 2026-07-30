import { Link } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { directionsIntro } from "../data"
import { BoundaryRail } from "../components/BoundaryRail"

/*
 * Directions (isDirections). A design gallery showing the three result-header
 * treatments: A (ledger), B (boundary rail), C (two sentences on a dark panel).
 */
function DirectionLabel({
  letter,
  title,
  note,
}: {
  letter: string
  title: string
  note: string
}) {
  return (
    <div className="flex items-baseline gap-2.5">
      <span className="font-mono text-[11px] bg-ink text-bg px-2 py-[3px] rounded-[5px]">
        {letter}
      </span>
      <span className="text-[13.5px] font-medium">{title}</span>
      <span className="text-[12.5px] text-t2">{note}</span>
    </div>
  )
}

export function Directions() {
  return (
    <div className="lm-screen flex flex-col gap-[26px]">
      <div>
        <div className="font-serif text-[34px] leading-[1.1]">
          {directionsIntro.title}
        </div>
        <div className="text-[14px] text-t2 mt-2 max-w-[66ch] text-pretty">
          The result header is the emotional moment of the product - it is the
          screen a student opens after a mock. The app now uses{" "}
          <Link to="/student/result">A and B together</Link>: the ledger
          reading, with the boundary rail underneath it. C is kept here as the
          softest alternative.
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <DirectionLabel
          letter="A"
          title="Ledger - marks first, boundaries beside them"
          note="calm, teacherly, reads like a marked script"
        />
        <Card className="rounded-xl px-7 py-[26px]">
          <div className="font-mono text-[11.5px] text-t2">
            0625 / Paper 1 Variant 2 / May-June 2020
          </div>
          <div className="font-serif text-[32px] leading-[1.12] mt-[9px]">
            Thirty-eight out of forty.
          </div>
          <div className="flex gap-[26px] mt-5 items-end flex-wrap">
            <div>
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Marks
              </div>
              <div className="font-serif text-[38px] leading-[1.1]">
                38<span className="text-[20px] text-t2">/40</span>
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Grade
              </div>
              <div className="font-serif text-[38px] leading-[1.1] text-accent">
                A
              </div>
            </div>
            <div className="flex-1 border-l border-border pl-6 text-[13px] text-t2 leading-[1.5] max-w-[44ch] text-pretty">
              Above the 2020 A boundary by 15 marks. Two dropped, both
              single-mark recall.
            </div>
          </div>
        </Card>

        <DirectionLabel
          letter="B"
          title="Boundary rail - where you sit on the curve"
          note="the grade becomes a position, not a verdict"
        />
        <Card className="rounded-xl px-7 py-[26px]">
          <div className="flex justify-between items-baseline">
            <div className="font-serif text-[30px]">Physics - Paper 1</div>
            <div className="font-mono text-[12px] text-t2">
              2020 boundaries - 95%
            </div>
          </div>
          <BoundaryRail pct={95} />
          <div className="text-[13px] text-t2 mt-2.5 text-pretty">
            Fifteen marks of headroom above A. Even a bad day keeps you in the
            band.
          </div>
        </Card>

        <DirectionLabel
          letter="C"
          title="Two sentences - the grade is secondary"
          note="warmest; for anxious students, boundary detail one level down"
        />
        <div className="bg-ink text-bg rounded-xl px-[30px] py-[34px]">
          <div className="font-serif text-[34px] leading-[1.28] max-w-[26ch]">
            You are marking at grade A, and the only two marks you lost were the
            same kind of question.
          </div>
          <div className="flex gap-[26px] mt-[26px] items-center">
            <div className="font-mono text-[12px] opacity-60">
              0625/12 - 38/40 - 95%
            </div>
            <div className="flex-1" />
            <button className="border border-[oklch(0.42_0.02_35)] bg-transparent text-inherit font-sans text-[12.5px] px-[15px] py-[9px] rounded-lg cursor-pointer">
              Show the marking detail
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
