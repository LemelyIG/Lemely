/**
 * The mock's `.fld` look on the kit's Input and Textarea: a 16px-radius field with a 1.5px outline that
 * becomes the 2px primary border on focus, and the 13px label above it. The kit draws a 1px border, so
 * it is zeroed here and the inset shadow stands in for it. The radius is restated `!` on focus-visible
 * because index.css has an unlayered `:focus-visible { border-radius: 2px }` that would square the field
 * the moment a keyboard user lands on it.
 */
export const FIELD_WRAPPER = "grid gap-1.5"
export const FIELD_LABEL = "text-[13px] font-semibold leading-tight text-on-surface-variant"
export const FIELD_CONTROL =
  "rounded-2xl border-0 px-3.5 py-3 text-[16px] font-medium leading-[1.5] shadow-[inset_0_0_0_1.5px_var(--color-outline)] focus-visible:!rounded-[16px] focus-visible:shadow-[inset_0_0_0_2px_var(--color-primary)]"
/** Card sides are Mono: they are the words being learned, not interface text. */
export const FIELD_MONO = `${FIELD_CONTROL} font-mono resize-none`
