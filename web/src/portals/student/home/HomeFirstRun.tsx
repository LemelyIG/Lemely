import { Camera, ChartBar, Target } from "@phosphor-icons/react"
import { Walkthrough } from "@/components/redesign"
import { cn } from "@/lib/utils"

/*
 * First run: the stage already says "Let's mark your first paper" with the
 * one action. Below it, a ghost floor shows where grades will sit, and three
 * short steps say what happens next (states-r1 RQ3 pattern).
 */
export function HomeFirstRun() {
  return (
    <div className="grid gap-4">
      <div aria-hidden="true" className="grid grid-cols-3 border-y border-outline-variant py-3.5">
        {[0, 1, 2].map((i) => (
          <div key={i} className={cn("grid justify-items-center gap-1.5", i > 0 && "border-s border-outline-variant")}>
            <span className="h-11 w-9 rounded-row bg-surface-container-high" />
            <span className="h-3 w-16 rounded-bar bg-surface-container-high" />
          </div>
        ))}
      </div>
      <Walkthrough
        steps={[
          { icon: Camera, title: "Scan a paper you've sat", body: "Lemely marks it question by question." },
          { icon: ChartBar, title: "See your grades", body: "Real grade boundaries, per subject." },
          { icon: Target, title: "Win marks back", body: "Practice built from your own mistakes." },
        ]}
      />
    </div>
  )
}
