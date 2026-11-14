/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, MagnifyingGlass, Plus } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ALL_SUBJECTS,
  MAX_OTHER_SUBJECTS,
  MAX_OTHER_SUBJECT_LENGTH,
  type WaitlistSubject,
} from '@/lib/waitlist-api'

/**
 * Searchable multi-select over the whole subject catalogue, opened by the "Other" chip.
 *
 * ARIA combobox pattern with a multiselectable listbox: focus stays in the input and the
 * highlighted option is named by `aria-activedescendant`. Options are 44px. When the typed
 * text matches nothing in the catalogue, the last row offers `Add "<text>"`, which becomes a
 * free-text subject (the server's `otherSubjects`).
 *
 * Escape closes the picker only. The dialog must not close with it, so the owner passes an
 * `escapeGuard` ref the dialog consults before it handles the same key.
 */
export function SubjectPicker({
  selected,
  others,
  onToggle,
  onAddOther,
  onClose,
  escapeGuard,
}: {
  selected: readonly WaitlistSubject[]
  others: readonly string[]
  onToggle: (value: WaitlistSubject) => void
  onAddOther: (text: string) => void
  onClose: () => void
  escapeGuard?: { current: (() => boolean) | null }
}) {
  const uid = useId()
  const listId = `${uid}-list`
  const input = useRef<HTMLInputElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    input.current?.focus()
    root.current?.scrollIntoView({ block: 'nearest' })
    if (escapeGuard) escapeGuard.current = () => !!root.current?.contains(document.activeElement)
    return () => {
      if (escapeGuard) escapeGuard.current = null
    }
  }, [escapeGuard])

  const text = query.trim()
  const matches = useMemo(
    () => ALL_SUBJECTS.filter((s) => s.label.toLowerCase().includes(text.toLowerCase())),
    [text],
  )
  const canAdd =
    text.length > 0 &&
    text.length <= MAX_OTHER_SUBJECT_LENGTH &&
    others.length < MAX_OTHER_SUBJECTS &&
    !ALL_SUBJECTS.some((s) => s.label.toLowerCase() === text.toLowerCase()) &&
    !others.some((o) => o.toLowerCase() === text.toLowerCase())
  const rows = matches.length + (canAdd ? 1 : 0)
  const at = Math.min(active, Math.max(rows - 1, 0))
  const optionId = (i: number) => `${uid}-opt-${i}`

  function choose(i: number) {
    if (i < matches.length) onToggle(matches[i].value)
    else if (canAdd) {
      onAddOther(text)
      setQuery('')
      setActive(0)
    }
  }

  /** Options are not tab stops (focus stays in the input), but a screen reader's virtual cursor can land on one. */
  function optionKey(e: React.KeyboardEvent<HTMLLIElement>, i: number) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      choose(i)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive(Math.min(rows - 1, at + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(Math.max(0, at - 1))
    } else if (e.key === 'Home') {
      setActive(0)
    } else if (e.key === 'End') {
      setActive(Math.max(rows - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (rows) choose(at)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  useEffect(() => {
    document.getElementById(optionId(at))?.scrollIntoView({ block: 'nearest' })
  }, [at]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={root} className="lw-picker flex flex-col gap-2 border-y border-outline-variant py-3">
      <Input
        ref={input}
        label="Search all subjects"
        labelClassName="sr-only"
        leadingIcon={<MagnifyingGlass size={18} aria-hidden />}
        className="min-h-11"
        role="combobox"
        aria-expanded="true"
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={rows ? optionId(at) : undefined}
        autoComplete="off"
        type="text"
        placeholder="Type to search, or add your own"
        value={query}
        maxLength={MAX_OTHER_SUBJECT_LENGTH}
        onChange={(e) => {
          setQuery(e.target.value)
          setActive(0)
        }}
        onKeyDown={onKeyDown}
      />
      <ul
        id={listId}
        role="listbox"
        aria-multiselectable="true"
        aria-label="Subjects, A to Z"
        className="lw-scrollbody m-0 flex max-h-[264px] list-none flex-col gap-0.5 p-0"
      >
        {matches.map((s, i) => {
          const on = selected.includes(s.value)
          return (
            <li
              key={s.value}
              id={optionId(i)}
              role="option"
              aria-selected={on}
              data-active={i === at}
              onMouseDown={(e) => e.preventDefault()}
              tabIndex={-1}
              onClick={() => choose(i)}
              onKeyDown={(e) => optionKey(e, i)}
              className="lw-option"
            >
              <span className="lw-option-box" data-on={on} aria-hidden>
                {on ? <Check size={12} weight="bold" /> : null}
              </span>
              {s.label}
            </li>
          )
        })}
        {canAdd ? (
          <li
            id={optionId(matches.length)}
            role="option"
            aria-selected="false"
            data-active={matches.length === at}
            onMouseDown={(e) => e.preventDefault()}
            tabIndex={-1}
            onClick={() => choose(matches.length)}
            onKeyDown={(e) => optionKey(e, matches.length)}
            className="lw-option"
          >
            <span className="lw-option-box" aria-hidden>
              <Plus size={12} weight="bold" />
            </span>
            Add "{text}"
          </li>
        ) : null}
        {rows === 0 ? (
          <li role="presentation" className="px-3 py-3 text-body-sm text-on-surface-variant">
            {text.length > MAX_OTHER_SUBJECT_LENGTH || others.length >= MAX_OTHER_SUBJECTS
              ? `You can add up to ${MAX_OTHER_SUBJECTS} of your own subjects.`
              : 'No match.'}
          </li>
        ) : null}
      </ul>
      <div className="flex items-center justify-between gap-2">
        <span className="text-body-sm text-on-surface-variant" aria-live="polite">
          {selected.length + others.length} picked
        </span>
        <Button type="button" variant="secondary" className="min-h-11" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  )
}
