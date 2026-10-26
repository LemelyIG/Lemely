/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the rating is one real radio group with a filled-star shape and a spoken count, never colour; the privacy line stays put under the text, so it is clear but unadorned. */
import { useId, useState } from "react"
import { Star } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Textarea } from "@/components/ui/textarea"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import {
  REVIEW_PRIVACY_LINE,
  REVIEW_TEXT_MAX,
  reviewCreateBody,
  reviewUpdateBody,
  sessionActionError,
} from "@/lib/tutoring/sessionView"
import { cn } from "@/lib/utils"
import type { ReviewCreate, ReviewUpdate } from "@/lib/tutoringTypes"

/*
 * Review form (SPEC §d S-37, routes S6 and S7). Stars, optional text, and the
 * line that says what happens to the text.
 *
 *   - The rating is a native radio group (`fieldset` + `legend`), so arrow keys
 *     move within it and a screen reader hears "3 stars, 3 of 5". Each star is a
 *     44 px target; the chosen ones are filled shapes, not just a colour, and the
 *     count is repeated in words beside them.
 *   - Stars are required and nothing else is. Until one is chosen the line under
 *     them says so; the button stays enabled in create mode so pressing it
 *     explains rather than sitting dead.
 *   - Text is plain text, at most 1000 characters (the database's limit). A
 *     refused contact detail is worded by the SPEC §d sentence and sits on the
 *     field; any other failure is an alert line.
 *   - Editing: the booking carries the stars but not the old text, so the text
 *     box starts empty and means "replace", and "Remove my review text" clears
 *     it. Nothing is sent when nothing changed (the API would refuse it).
 *
 * Wording and request bodies are `lib/tutoring/sessionView.ts`, where they are
 * tested. The screen owns the mutation and closes the form when it succeeds.
 */

interface BaseProps {
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
}

export interface ReviewCreateFormProps extends BaseProps {
  mode: "create"
  onSubmit: (body: ReviewCreate) => void
}

export interface ReviewEditFormProps extends BaseProps {
  mode: "edit"
  initialStars: number
  /** Whether the review has text that "Remove my review text" could clear. */
  hasText: boolean
  onSubmit: (body: ReviewUpdate) => void
  onCancel: () => void
}

export type ReviewFormProps = ReviewCreateFormProps | ReviewEditFormProps

const STAR_VALUES = [1, 2, 3, 4, 5] as const

function StarPicker({
  value,
  onChange,
  disabled,
  invalid,
}: {
  value: number
  onChange: (stars: number) => void
  disabled: boolean
  invalid: boolean
}) {
  const name = useId()
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0" disabled={disabled}>
      <legend className="mb-1 p-0 text-label text-ink">Your rating</legend>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <div className="flex items-center">
          {STAR_VALUES.map((stars) => {
            const filled = stars <= value
            return (
              <label
                key={stars}
                className={cn(
                  "relative inline-flex size-11 cursor-pointer items-center justify-center rounded-md",
                  "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus-ring",
                  "has-disabled:cursor-not-allowed has-disabled:opacity-50",
                )}
              >
                <input
                  type="radio"
                  name={name}
                  value={stars}
                  checked={value === stars}
                  onChange={() => onChange(stars)}
                  className="peer sr-only"
                  aria-label={`${stars} ${stars === 1 ? "star" : "stars"}`}
                />
                <Star
                  size={28}
                  weight={filled ? "fill" : "regular"}
                  className={cn(filled ? "text-pastel-amber-ink" : "text-ink-faint")}
                  aria-hidden
                />
              </label>
            )
          })}
        </div>
        <span className={cn("text-body-sm", invalid ? "text-err" : "text-ink-muted")} aria-live="polite">
          {value > 0 ? `${value} of 5 stars` : "Choose 1 to 5 stars."}
        </span>
      </div>
    </fieldset>
  )
}

export function ReviewForm(props: ReviewFormProps) {
  const { pending = false, error } = props
  const edit = props.mode === "edit"
  const initialStars = props.mode === "edit" ? props.initialStars : 0
  const [stars, setStars] = useState(initialStars)
  const [text, setText] = useState("")
  const [clearText, setClearText] = useState(false)
  const [showMissing, setShowMissing] = useState(false)

  const errorText = sessionActionError(error, "review")
  const contactRefused = isTutoringError(error, "contact_details_not_allowed")
  const update = props.mode === "edit" ? reviewUpdateBody({ initialStars, stars, text, clearText }) : null

  function submit() {
    if (props.mode === "create") {
      if (stars < 1) {
        setShowMissing(true)
        return
      }
      props.onSubmit(reviewCreateBody(stars, text))
      return
    }
    if (update !== null) props.onSubmit(update)
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <StarPicker value={stars} onChange={setStars} disabled={pending} invalid={showMissing && stars < 1} />

      <div className="flex flex-col gap-2">
        <Textarea
          label={edit ? "Replace your review text (optional)" : "Your review (optional)"}
          value={text}
          maxLength={REVIEW_TEXT_MAX}
          rows={4}
          autoResize
          disabled={pending || clearText}
          onChange={(event) => setText(event.target.value)}
          error={contactRefused ? (errorText ?? undefined) : undefined}
          hint={edit ? "Leave it empty to keep what you wrote." : undefined}
        />
        {props.mode === "edit" && props.hasText ? (
          <Checkbox
            label="Remove my review text"
            checked={clearText}
            disabled={pending}
            onChange={(event) => {
              setClearText(event.target.checked)
              if (event.target.checked) setText("")
            }}
          />
        ) : null}
        <p className="m-0 max-w-prose text-body-sm text-ink-muted">{REVIEW_PRIVACY_LINE}</p>
      </div>

      {errorText && !contactRefused ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {errorText}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        {props.mode === "edit" ? (
          <Button type="button" variant="secondary" size="sm" onClick={props.onCancel} disabled={pending}>
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={pending}
          disabled={props.mode === "edit" && update === null}
        >
          {edit ? "Save changes" : "Send review"}
        </Button>
      </div>
    </form>
  )
}
