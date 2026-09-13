import { ArrowLeft } from "@phosphor-icons/react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { backTarget } from "@/lib/nav/backTarget"

/*
 * Packet B2a · the one back control below the `sidebar` breakpoint, where
 * there is no sidebar navigation to fall back on. Renders in the student
 * header ahead of `Breadcrumbs` whenever the trail is more than one deep.
 *
 * Resolves through `backTarget`: real history (`navigate(-1)`) when this tab
 * has some to go back to, otherwise `fallback` — a deep link followed
 * directly has no in-app history, and `navigate(-1)` there would leave the
 * app rather than take the reader up a level.
 */
export function BackControl({
  fallback,
  label = "Back",
  className,
}: {
  fallback: string
  label?: string
  className?: string
}) {
  const navigate = useNavigate()

  function handleClick() {
    const target = backTarget(window.history.state?.idx, fallback)
    if (target.kind === "history") {
      // react-router's delta overload (`navigate(-1)`) calls `router.go()`
      // directly and ignores an options argument entirely — `viewTransition`
      // only exists on the `to`-argument overload's `NavigateOptions`, so a
      // real history pop plays no View Transition here. The route fallback
      // below is the one branch that can actually request one.
      navigate(-1)
    } else {
      navigate(target.to, { replace: true, viewTransition: true })
    }
  }

  return (
    <Button variant="ghost" size="sm" onClick={handleClick} className={className}>
      <ArrowLeft size={18} aria-hidden="true" />
      {label}
    </Button>
  )
}
