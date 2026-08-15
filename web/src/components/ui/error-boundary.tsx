import { Component, type ErrorInfo, type ReactNode } from "react"
import { ArrowClockwise, WarningCircle } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"

/*
 * Real React error boundary. The Phase 1 audit found none anywhere in the
 * product, which means today an uncaught render error in any single widget
 * (a chart, a marking panel, a third-party embed) unmounts the entire React
 * tree and leaves the student or teacher looking at a blank white page with
 * no way back except a full reload. This component is the backstop.
 *
 * Error boundaries are one of the few remaining class-component requirements
 * in React: there is no hook equivalent of `getDerivedStateFromError` /
 * `componentDidCatch`, so this is deliberately a class despite every other
 * component in the kit being a function. It only ever catches errors thrown
 * during render, in lifecycle methods, and in constructors of the tree
 * below it — NOT errors in event handlers, async code, or SSR — callers with
 * those need their own try/catch, this component cannot see them.
 *
 * Copy voice matches `error-state.tsx`: active voice, plain, no blame, no
 * exclamation marks, no em-dashes, sentence case.
 */

export interface ErrorBoundaryProps {
  children: ReactNode
  /**
   * Rendered instead of the default fallback panel when supplied. Receives
   * the caught error and a `reset` callback that clears the boundary's error
   * state and re-renders `children` fresh — useful for a caller that wants a
   * fallback scoped to its own layout (e.g. inline within a card) rather than
   * the boundary's generic full-panel default.
   */
  fallback?: (error: Error, reset: () => void) => ReactNode
  /**
   * Called with the error and React's component-stack info whenever the
   * boundary catches something, for logging. No default: this component
   * does not assume a logging backend exists, so a caught error is silent
   * unless the caller wires this up.
   */
  onError?: (error: Error, info: ErrorInfo) => void
  /**
   * One-line label for what this boundary protects, shown in the default
   * fallback ("This panel", "The results chart", …) so the message names
   * what broke instead of a bare generic string. Defaults to "This section".
   */
  label?: string
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info)
  }

  /** Clears the caught error and lets React attempt to render `children`
   * again. Does not touch whatever caused the original throw — a caller
   * whose data was the problem should refetch before or during `reset`
   * via its own `onError`/state, not rely on this alone to fix anything. */
  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (error === null) {
      return this.props.children
    }

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    const label = this.props.label ?? "This section"

    return (
      <div
        role="alert"
        className="mx-auto flex w-full max-w-sm flex-col items-center gap-3 rounded-lg border border-rule bg-paper-raised px-6 py-10 text-center"
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-err-wash">
          <WarningCircle size={22} className="text-err" aria-hidden="true" />
        </div>
        <div className="flex flex-col gap-1.5">
          <p className="text-body-lg font-medium text-ink">
            {label} ran into a problem
          </p>
          <p className="text-body-md text-ink-muted">
            We couldn't display this. Reloading it usually fixes the problem.
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={this.reset}
          className="mt-1 gap-1.5"
        >
          <ArrowClockwise size={16} aria-hidden="true" />
          Try again
        </Button>
      </div>
    )
  }
}
