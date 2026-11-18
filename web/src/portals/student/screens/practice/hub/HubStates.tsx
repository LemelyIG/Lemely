/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Link } from "react-router-dom"
import { Binny, BinnyLine, GhostRows, Walkthrough } from "@/components/redesign"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { PaperIcon, SetIcon, TestIcon } from "../practiceIcons"

/** The mock's big call to action. Its lift is the `shadow-hover` token, the nearest to the mock's off-token shadow. */
const BIG_CTA = "min-h-[54px] w-full max-w-[300px] rounded-[18px] text-[16px] shadow-hover"

/** CL: the tile grid, a heading bar and three ghost rows, in the real layout's shape. */
export function HubSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading practice" className="grid gap-3.5">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3">
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-[124px] rounded-[20px] lg:h-[140px]" />
        ))}
      </div>
      <SkeletonBlock className="mt-2 h-[22px] w-40" />
      <GhostRows rows={3} />
    </div>
  )
}

/** CE: the tiles stay above this; only the topic-driven parts failed. */
export function HubError({ onRetry, retrying }: { onRetry: () => void; retrying: boolean }) {
  return (
    <div role="alert" className="grid justify-items-center gap-3 px-2 pt-2 pb-6 text-center">
      <Binny mood="sad" size={80} motion="none" />
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
        We couldn’t load your topics
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">
        The tiles still work. Check your connection for the rest.
      </p>
      <Button variant="primary" size="lg" className={BIG_CTA} loading={retrying} onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/** CZ: Binny opens, three steps say what happens, one call to action. */
export function FirstRun({ line }: { line: string }) {
  return (
    <div className="grid gap-5">
      <BinnyLine mood="open" line={line} size={64} motion="pop" />
      <Walkthrough
        steps={[
          { icon: PaperIcon, title: "Scan a marked paper", body: "Or take the 10-minute placement test." },
          { icon: TestIcon, title: "See where marks went", body: "Your weakest topics show up here." },
          { icon: SetIcon, title: "Win them back", body: "Short sets, checked as you go." },
        ]}
      />
      <Link to="/student/correct" className={buttonVariants({ variant: "primary", size: "lg", className: cn(BIG_CTA, "max-w-none") })}>
        Scan a paper
      </Link>
    </div>
  )
}
