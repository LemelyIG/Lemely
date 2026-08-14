import {
  createContext,
  useContext,
  useId,
  useMemo,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"

/*
 * Accessible tabs: roving tabindex + arrow-key navigation over
 * `role="tablist"`/`role="tab"`/`role="tabpanel"`, per the WAI-ARIA Tabs
 * pattern. "Roving tabindex" means only the active tab is in the Tab-key
 * sequence (`tabIndex={0}`); every other tab is `tabIndex={-1}` and reachable
 * with the arrow keys once the tablist has focus — that's the mechanism that
 * lets a keyboard user Tab past a 6-tab row in one keystroke instead of six.
 *
 * Composed as three pieces (`Tabs`, `TabsList`+`Tab`, `TabsPanel`) sharing
 * context, matching the compound-component shape already used by other
 * multi-part primitives in this kit rather than one prop-heavy component.
 */

interface TabsContextValue {
  value: string
  setValue: (value: string) => void
  idPrefix: string
  registerTab: (value: string, node: HTMLButtonElement | null) => void
  /** Live map of mounted tab nodes, keyed by value. Read by `TabsList`'s
   * arrow-key handler to move DOM focus onto a sibling tab after selecting
   * it. Kept out of React state deliberately — it's an imperative focus
   * target, not something a re-render should ever be triggered by. */
  nodes: Map<string, HTMLButtonElement>
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabsContext(component: string): TabsContextValue {
  const ctx = useContext(TabsContext)
  if (!ctx) {
    throw new Error(`${component} must be used inside <Tabs>`)
  }
  return ctx
}

export interface TabsProps {
  /** Currently active tab's value. Controlled — the caller owns state, since
   * every real usage (query-param-synced tabs, wizard steps) needs to read
   * or drive the active tab from outside anyway. */
  value: string
  onValueChange: (value: string) => void
  children: ReactNode
  className?: string
}

export function Tabs({ value, onValueChange, children, className }: TabsProps) {
  const idPrefix = useId()
  const nodesRef = useRef(new Map<string, HTMLButtonElement>())

  const registerTab = (tabValue: string, node: HTMLButtonElement | null) => {
    if (node) nodesRef.current.set(tabValue, node)
    else nodesRef.current.delete(tabValue)
  }

  const contextValue = useMemo<TabsContextValue>(
    () => ({
      value,
      setValue: onValueChange,
      idPrefix,
      registerTab,
      nodes: nodesRef.current,
    }),
    [value, onValueChange, idPrefix],
  )

  return (
    <TabsContext.Provider value={contextValue}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

export interface TabDefinition {
  value: string
  label: ReactNode
  disabled?: boolean
}

export interface TabsListProps {
  tabs: TabDefinition[]
  /** Accessible name for the tablist itself, e.g. "Result sections". */
  label: string
  className?: string
}

/**
 * Renders the full row of tabs from a declarative list. Handles the arrow-key
 * roving-tabindex behaviour (Left/Right or Up/Down move focus and, per the
 * WAI-ARIA "automatic activation" variant, also select — the simpler and more
 * common tabs behaviour, matching e.g. browser devtools panels). Home/End
 * jump to the first/last enabled tab.
 */
export function TabsList({ tabs, label, className }: TabsListProps) {
  const { value, setValue, idPrefix, registerTab, nodes } = useTabsContext("TabsList")

  function focusAndSelect(nextValue: string) {
    setValue(nextValue)
    nodes.get(nextValue)?.focus()
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const enabled = tabs.filter((t) => !t.disabled)
    if (enabled.length === 0) return
    const currentIndex = enabled.findIndex((t) => t.value === value)

    let nextIndex: number | null = null
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        nextIndex = currentIndex === -1 ? 0 : (currentIndex + 1) % enabled.length
        break
      case "ArrowLeft":
      case "ArrowUp":
        nextIndex =
          currentIndex === -1
            ? enabled.length - 1
            : (currentIndex - 1 + enabled.length) % enabled.length
        break
      case "Home":
        nextIndex = 0
        break
      case "End":
        nextIndex = enabled.length - 1
        break
      default:
        return
    }
    event.preventDefault()
    focusAndSelect(enabled[nextIndex].value)
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={handleKeyDown}
      className={cn(
        "flex items-center gap-1 border-b border-rule",
        className,
      )}
    >
      {tabs.map((tab) => {
        const selected = tab.value === value
        return (
          <button
            key={tab.value}
            ref={(node) => registerTab(tab.value, node)}
            role="tab"
            type="button"
            id={`${idPrefix}-tab-${tab.value}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${tab.value}`}
            aria-disabled={tab.disabled || undefined}
            tabIndex={selected ? 0 : -1}
            disabled={tab.disabled}
            onClick={() => !tab.disabled && setValue(tab.value)}
            className={cn(
              "relative -mb-px shrink-0 px-3 py-2.5 text-label",
              // §9.2's press, which this control did not have: a tab is a real
              // `<button>` and the only thing that told you it had registered
              // the tap was the panel changing underneath.
              "transition-[color,transform] active:scale-[0.98]",
              "disabled:pointer-events-none disabled:opacity-50",
              selected
                ? "border-b-2 border-accent text-ink"
                : "border-b-2 border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

export interface TabsPanelProps {
  value: string
  children: ReactNode
  className?: string
}

/** Content pane for one tab. Only renders (and stays mounted) while its
 * `value` matches the active tab — unmounting inactive panels rather than
 * hiding them with CSS keeps their contents out of the tab order and out of
 * `find`/`Ctrl+F` matches for tabs the user isn't looking at. */
export function TabsPanel({ value, children, className }: TabsPanelProps) {
  const { value: activeValue, idPrefix } = useTabsContext("TabsPanel")
  if (value !== activeValue) return null

  return (
    <div
      role="tabpanel"
      id={`${idPrefix}-panel-${value}`}
      aria-labelledby={`${idPrefix}-tab-${value}`}
      tabIndex={0}
      className={cn(
        "motion-safe:animate-[lm-in_var(--dur-fast)_var(--ease-out-soft)_both]",
        className,
      )}
    >
      {children}
    </div>
  )
}
