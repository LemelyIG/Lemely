/* Hallmark · pre-emit critique: P4 H5 E5 S4 R5 V4 */
import { ArrowLeft } from "@phosphor-icons/react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { backTarget } from "@/lib/nav/backTarget"
import type { NavDirectionState } from "@/lib/nav/navDirectionState"

/** The history-or-fallback back action, shared by BackControl and the native bar's NativeBack. */
export function useBackAction(fallback: string): () => void {
  const navigate = useNavigate()
  return () => {
    const target = backTarget(window.history.state?.idx, fallback)
    if (target.kind === "history") {
      // react-router's delta overload (`navigate(-1)`) takes no options, so there is no `viewTransition`
      // to request here. A POP still gets one: React Router 7 replays a view transition on a POP whose
      // destination entry ever started one, and the direction reads "back". The route fallback below is
      // the branch that requests its own.
      navigate(-1)
    } else {
      // A replace reads as forward to the router; the person pressed back, so the state says so.
      navigate(target.to, { replace: true, viewTransition: true, state: { navDirection: "back" } satisfies NavDirectionState })
    }
  }
}

/*
 * Packet B2a · the one back control below the `sidebar` breakpoint on the
 * flat (non-native) frame, where there is no sidebar navigation to fall back
 * on. On native phones (iOS/Android) the bar's NativeBack is that control.
 * Renders in the student
 * shell's top bar (`portals/student/shell.tsx`, `shell-lg:hidden`) whenever
 * the shell trail is more than one deep.
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
  const handleClick = useBackAction(fallback)

  return (
    <Button variant="ghost" size="sm" onClick={handleClick} className={className}>
      <ArrowLeft size={18} aria-hidden="true" />
      {label}
    </Button>
  )
}
