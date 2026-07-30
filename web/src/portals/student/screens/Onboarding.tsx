import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { onboardChips, onboardHeader, onboardSteps, sliders } from "../data"

/*
 * Onboarding (isOnboard). A centred multi-step form: progress segments, four
 * confidence sliders (read-only visual state from the mock), and a multi-select
 * chip group.
 */
export function Onboarding() {
  return (
    <div className="lm-screen max-w-[760px] mx-auto flex flex-col gap-6">
      <div className="flex gap-1.5">
        {onboardSteps.map((s, i) => (
          <div
            key={i}
            className={`flex-1 h-[3px] rounded-[2px] ${s.done ? "bg-accent" : "bg-[oklch(0.90_0.01_40)]"}`}
          />
        ))}
      </div>
      <div>
        <div className="font-mono text-[11.5px] text-t2">
          {onboardHeader.step}
        </div>
        <div className="font-serif text-[36px] leading-[1.15] mt-2">
          {onboardHeader.title}
        </div>
        <div className="text-[14px] text-t2 mt-[9px] text-pretty">
          {onboardHeader.intro}
        </div>
      </div>

      <Card className="p-6 flex flex-col gap-[22px]">
        {sliders.map((s) => (
          <div key={s.label}>
            <div className="flex items-baseline gap-2.5 mb-[11px]">
              <div className="text-[13.5px] font-medium">{s.label}</div>
              {s.code ? (
                <div className="font-mono text-[11.5px] text-t2">{s.code}</div>
              ) : null}
              <div className="flex-1" />
              <div className="text-[12.5px] text-accent">{s.word}</div>
            </div>
            <div className="relative h-[26px] flex items-center">
              <div className="absolute left-0 right-0 h-[5px] rounded-[3px] bg-surface-2" />
              <div
                className="absolute left-0 h-[5px] rounded-[3px] bg-accent"
                style={{ width: `${s.pct}%` }}
              />
              <div
                className="absolute w-[18px] h-[18px] -ml-[9px] rounded-full bg-surface border-2 border-accent shadow-[0_1px_4px_oklch(0.2_0.02_35/.16)]"
                style={{ left: `${s.pct}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px] text-t3 mt-[5px]">
              <span>{s.low}</span>
              <span>{s.high}</span>
            </div>
          </div>
        ))}
      </Card>

      <Card className="p-[22px]">
        <div className="text-[13.5px] font-medium mb-[5px]">
          Which of these describes your last exam week?
        </div>
        <div className="text-[12.5px] text-t2 mb-[15px]">
          Pick as many as fit.
        </div>
        <div className="flex flex-wrap gap-[9px]">
          {onboardChips.map((c) => (
            <div
              key={c.label}
              className={`border rounded-[20px] px-[15px] py-2 text-[12.5px] cursor-pointer ${
                c.active
                  ? "border-accent bg-accent-subtle text-[oklch(0.38_0.07_35)]"
                  : "border-border bg-surface text-t2"
              }`}
            >
              {c.label}
            </div>
          ))}
        </div>
      </Card>

      <div className="flex gap-3 items-center">
        <Button variant="accent" size="lg">
          Continue
        </Button>
        <button className="border-0 bg-transparent text-t2 font-sans text-[13px] cursor-pointer">
          Skip - I'll take the placement test first
        </button>
      </div>
    </div>
  )
}
