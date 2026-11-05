/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import {
  Suspense,
  useCallback,
  useEffect,
  useId,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { X } from "@phosphor-icons/react"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { portalErrorFallback } from "@/components/route-error"
import { lockScroll } from "@/lib/scrollLock"
import { overlayCloseAction } from "@/lib/nav/backgroundLocation"
import { cn } from "@/lib/utils"
import { activeSettingsTab, settingsTabPath, type SettingsTab } from "./settingsTabs"
import { SettingsHeadingLevel } from "./SettingsRows"

/*
 * Settings as a floating dialog over the page the reader was on.
 *
 * `SettingsModal` is the frame: a centred dialog with a tab rail on wide
 * screens, a full-height sheet with scrollable top tabs on phones. It owns
 * the dialog contract (aria-modal, a label, focus moved in and trapped,
 * Escape and the scrim close it, focus goes back where it came from, the
 * page behind does not scroll) and nothing about routing, so any portal can
 * adopt it.
 *
 * Why not the kit `Modal`: `Modal` pushes its own history entry so Back
 * closes it. Here the URL already is the dialog (each tab is a route), so a
 * second entry would make Back step through a phantom state first. The
 * dialog behaviour is re-stated here against the route instead.
 *
 * `SettingsModalRoute` is the route element: it reads the active tab from
 * the URL, renders the tab's route as the panel, and turns "close" into the
 * right history move (`overlayCloseAction`).
 *
 * Tabs are `NavLink`s with `aria-current="page"`, not ARIA tabs: each tab is
 * a separate route, and claiming a tabpanel relationship the router does not
 * implement is worse for a screen reader than plain links. Switching tabs
 * replaces the history entry, so Back closes the dialog rather than walking
 * back through every tab visited.
 */

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

function isShown(element: HTMLElement): boolean {
  return element.getClientRects().length > 0
}

/** The elements Tab actually stops on, in order: displayed, and for a radio
 * group only the checked radio (or the first, when none is checked), since
 * the browser skips the rest. */
function tabbable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    if (!isShown(element)) return false
    if (element instanceof HTMLInputElement && element.type === "radio" && element.name) {
      const group = Array.from(
        root.querySelectorAll<HTMLInputElement>(`input[type="radio"]`),
      ).filter((radio) => radio.name === element.name && !radio.disabled)
      const stop = group.find((radio) => radio.checked) ?? group[0]
      return stop === element
    }
    return true
  })
}

export interface SettingsModalProps {
  title: string
  tabs: readonly SettingsTab[]
  basePath: string
  /** The tab the URL points at; `null` renders no tab heading. */
  activeTab: SettingsTab | null
  onClose: () => void
  /** Router state carried on every tab link (the page underneath). */
  linkState?: unknown
  children: ReactNode
}

export function SettingsModal({
  title,
  tabs,
  basePath,
  activeTab,
  onClose,
  linkState,
  children,
}: SettingsModalProps) {
  const titleId = useId()
  const tabHeadingId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)

  // Focus in on open, back to the opener on close.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const raf = requestAnimationFrame(() => {
      const panel = panelRef.current
      if (!panel) return
      // The current tab first (the reader's place in the dialog), then the
      // first focusable control, then the panel itself.
      // Only one of the two tab navs is displayed at a time.
      const current = Array.from(
        panel.querySelectorAll<HTMLElement>('nav a[aria-current="page"]'),
      ).find(isShown)
      const first = tabbable(panel)[0]
      ;(current ?? first ?? panel).focus()
    })
    return () => {
      cancelAnimationFrame(raf)
      if (previouslyFocused && previouslyFocused.isConnected) previouslyFocused.focus()
    }
  }, [])

  useEffect(() => lockScroll(), [])

  // A new tab starts at the top of the panel, and the phone tab strip keeps
  // the current tab in view.
  useEffect(() => {
    contentRef.current?.scrollTo?.({ top: 0 })
    const current = panelRef.current?.querySelector<HTMLElement>(
      '[data-settings-tabs="strip"] a[aria-current="page"]',
    )
    current?.scrollIntoView?.({ block: "nearest", inline: "nearest" })
  }, [activeTab?.id])

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const panel = panelRef.current
    // Events from a nested dialog (a confirmation portalled to `body`) still
    // bubble here through the React tree; they are that dialog's to handle.
    if (!panel || !(event.target instanceof Node) || !panel.contains(event.target)) return
    if (event.key === "Escape") {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== "Tab") return
    const focusable = tabbable(panel)
    if (focusable.length === 0) {
      event.preventDefault()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const tabLinks = (variant: "rail" | "strip") =>
    tabs.map((tab) => (
      <NavLink
        key={tab.id}
        to={settingsTabPath(basePath, tab)}
        end
        replace
        state={linkState}
        className={({ isActive }) =>
          cn(
            "flex min-h-11 shrink-0 items-center rounded-md px-3 text-label transition-colors",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
            variant === "strip" ? "whitespace-nowrap" : null,
            isActive
              ? "bg-primary-container text-primary"
              : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface",
          )
        }
      >
        {tab.label}
      </NavLink>
    ))

  return createPortal(
    <div
      className="fixed inset-0 z-modal flex items-stretch justify-center md:items-center md:p-6"
      onKeyDown={handleKeyDown}
    >
      <div
        className="fixed inset-0 z-scrim bg-scrim motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-settings-dialog
        className={cn(
          "relative z-modal flex h-dvh w-full flex-col overflow-hidden bg-surface focus:outline-none",
          "md:h-[min(46rem,calc(100dvh-3rem))] md:max-w-240 md:flex-row md:rounded-card md:border md:border-outline-variant md:shadow-[var(--shadow-float)]",
          "motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-spring)_both]",
        )}
      >
        {/* Header: title and close on every width. On phones it also holds
            the scrollable tab strip; on wide screens it heads the rail. */}
        <div className="flex shrink-0 flex-col border-b border-outline-variant bg-surface-container-low md:w-64 md:border-e md:border-b-0">
          <div className="flex items-center justify-between gap-3 px-4 pt-[max(env(safe-area-inset-top),1rem)] pb-2 md:px-5 md:pt-6">
            <h2 id={titleId} className="text-display-md text-on-surface">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close settings"
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-on-surface-variant transition-colors md:hidden",
                "hover:bg-surface-container hover:text-on-surface active:scale-[0.98]",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              )}
            >
              <X size={20} aria-hidden="true" />
            </button>
          </div>
          <nav
            aria-label="Settings sections"
            data-settings-tabs="strip"
            className="flex gap-1 overflow-x-auto px-4 pt-1 pb-3 lm-scroll md:hidden"
          >
            {tabLinks("strip")}
          </nav>
          <nav
            aria-label="Settings sections"
            data-settings-tabs="rail"
            className="hidden flex-col gap-1 overflow-y-auto px-3 pb-6 md:flex"
          >
            {tabLinks("rail")}
          </nav>
        </div>

        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <div
            ref={contentRef}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain lm-scroll"
            aria-labelledby={activeTab ? tabHeadingId : undefined}
            role={activeTab ? "region" : undefined}
          >
            <div className="mx-auto flex w-full max-w-180 flex-col gap-8 px-4 pt-6 pb-[max(env(safe-area-inset-bottom),2rem)] md:px-10 md:pt-8 md:pb-10">
              {activeTab ? (
                <div className="flex flex-col gap-1 md:pe-12">
                  <h2 id={tabHeadingId} className="text-display-sm text-on-surface">
                    {activeTab.label}
                  </h2>
                  <p className="max-w-[60ch] text-body-sm text-on-surface-variant">
                    {activeTab.description}
                  </p>
                </div>
              ) : null}
              <SettingsHeadingLevel level={3}>{children}</SettingsHeadingLevel>
            </div>
          </div>
          {/* Wide screens: the close button sits top-right of the panel. After
              the scroller in source order, so it paints above it without a
              z-index of its own. */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className={cn(
              "absolute end-4 top-4 hidden h-11 w-11 items-center justify-center rounded-md bg-surface text-on-surface-variant transition-colors md:flex",
              "hover:bg-surface-container-low hover:text-on-surface active:scale-[0.98]",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
            )}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** `window.history.state.idx`, react-router's own entry index, or `null`
 * outside a browser history. */
function historyIndex(): number | null {
  if (typeof window === "undefined") return null
  const state: unknown = window.history.state
  if (typeof state === "object" && state !== null && "idx" in state) {
    const idx = (state as { idx: unknown }).idx
    return typeof idx === "number" ? idx : null
  }
  return null
}

export interface SettingsModalRouteProps {
  tabs: readonly SettingsTab[]
  basePath: string
  /** Where closing goes when there is no page to step back to. */
  fallbackPath: string
}

/** The route element for a portal's `settings` route: the dialog, with the
 * matched tab's route rendered inside it. */
export function SettingsModalRoute({ tabs, basePath, fallbackPath }: SettingsModalRouteProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const activeTab = activeSettingsTab(tabs, basePath, location.pathname)

  const close = useCallback(() => {
    const action = overlayCloseAction({
      state: location.state,
      historyIndex: historyIndex(),
      overlayBase: basePath,
      fallbackPath,
    })
    if (action.kind === "back") navigate(-1)
    else navigate(action.to, { replace: true })
  }, [location.state, basePath, fallbackPath, navigate])

  return (
    <SettingsModal
      title="Settings"
      tabs={tabs}
      basePath={basePath}
      activeTab={activeTab}
      onClose={close}
      linkState={location.state}
    >
      <Suspense fallback={<PanelSkeleton />}>
        <ErrorBoundary label="This section" resetKey={location.pathname} fallback={portalErrorFallback}>
          <Outlet />
        </ErrorBoundary>
      </Suspense>
    </SettingsModal>
  )
}
