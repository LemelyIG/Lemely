/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Link } from "react-router-dom"
import { Binny, BinnyLine, GhostRows, Walkthrough } from "@/components/redesign"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/ui/state-views"
import { cn } from "@/lib/utils"
import { PaperIcon, SetIcon, TestIcon } from "../practiceIcons"
import type { HubErrorKind } from "./hubModel"

/** The mock's big call to action. Its lift is the `shadow-hover` token, the nearest to the mock's off-token shadow. */
const BIG_CTA = "min-h-[54px] w-full max-w-[300px] rounded-[18px] text-[16px] font-bold shadow-hover"

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

/**
 * CE: the lists failed to load. The body only promises the tiles that still
 * open: with no subject to build from, the practice set and placement tiles are
 * paused, so the copy says so instead of claiming every tile works.
 */
export function HubError({
  kind,
  tilesWork,
  onRetry,
  retrying,
}: {
  kind: HubErrorKind
  /** The practice set tile can still open a builder. */
  tilesWork: boolean
  onRetry: () => void
  retrying: boolean
}) {
  const copy =
    kind === "subjects"
      ? {
          heading: "We couldn’t load your subjects",
          body: "Practice sets and the placement test need them. Flashcards and past papers still open.",
        }
      : {
          heading: "We couldn’t load your topics",
          body: tilesWork ? "Some practice options are still available. Check your connection for the rest." : "Check your connection and try again.",
        }
  return (
    <div role="alert" className="grid justify-items-center gap-3 px-2 pt-2 pb-6 text-center">
      <Binny mood="sad" size={80} motion="none" />
      <h2 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
        {copy.heading}
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] font-medium leading-[1.4] text-on-surface-variant">{copy.body}</p>
      <Button variant="primary" size="lg" className={BIG_CTA} loading={retrying} onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/**
 * Degraded, not failed: the lists below still work. One polite live region (the
 * compact `ErrorState` owns `role="status"`; nothing wraps it), and the retry is
 * a `Button` in its trailing slot so it can show it is working while it retries.
 */
export function HubNotice({
  kind,
  onRetry,
  retrying,
}: {
  kind: "subjects" | "refresh"
  onRetry: () => void
  retrying: boolean
}) {
  const copy =
    kind === "subjects"
      ? { heading: "Some subjects may be missing", body: "We couldn’t load your subjects, so these picks may be incomplete." }
      : { heading: "Couldn’t refresh practice", body: "Showing your last loaded information." }
  return (
    <ErrorState compact heading={copy.heading} body={copy.body}>
      <Button variant="ghost" size="sm" className="min-h-11 self-start" loading={retrying} onClick={onRetry}>
        Try again
      </Button>
    </ErrorState>
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
      {/* `cn` merges after the variant recipe: `buttonVariants`' own `className` only appends, so `rounded-md` and `font-medium` would sit beside the mock's 18px and 700 and win the tie. */}
      <Link to="/student/correct" className={cn(buttonVariants({ variant: "primary", size: "lg" }), BIG_CTA, "max-w-none lg:max-w-[360px]")}>
        Scan a paper
      </Link>
    </div>
  )
}
