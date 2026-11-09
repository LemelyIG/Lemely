/*
 * Class strings shared by the shell, each mapped from a design A rule in
 * web/dev-previews/student-home/variant-a.css (selector named on each).
 */

export const SHELL_FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** `.as-btn` */
const SHELL_BUTTON =
  "inline-flex h-9 flex-none cursor-pointer items-center gap-[7px] whitespace-nowrap rounded-chip px-3.5 btn-text transition-[transform,background-color] duration-150 active:scale-[0.97] pointer-coarse:min-h-11 " +
  SHELL_FOCUS_RING

/** `.as-btn-primary` */
export const SHELL_BUTTON_PRIMARY = `${SHELL_BUTTON} bg-primary text-on-primary hover:bg-primary-hover`

/** `.as-btn-tonal` */
export const SHELL_BUTTON_TONAL = `${SHELL_BUTTON} bg-secondary-container text-on-secondary-container hover:bg-[color-mix(in_oklch,var(--color-secondary-container),var(--color-primary)_8%)]`

/** `.as-iconbtn`, open state from Radix's `data-state`. */
export const SHELL_ICON_BUTTON =
  "lm-native-iconbtn relative grid size-9 flex-none cursor-pointer place-items-center rounded-chip text-on-surface-variant transition-colors duration-150 hover:bg-surface-container-low hover:text-on-surface data-[state=open]:bg-surface-container-low data-[state=open]:text-on-surface pointer-coarse:size-11 " +
  SHELL_FOCUS_RING

/** `.as-pop-panel` (+ its ≤720px inset rule). `!rounded-inner`: Radix focuses the
 * panel on open, and the unlayered global `:focus-visible` sets a 2px radius.
 * `max-shell-sm:-mt-2`: on phones design A drops the panel from the 44px bar,
 * 4px above its bottom (`calc(100% - 4px)`), not 8px below the 36px trigger. */
export const SHELL_PANEL =
  "z-dropdown w-80 !rounded-inner bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-panel)] dark:bg-surface-container-highest dark:shadow-[0_0_0_1px_var(--color-outline)] max-shell-sm:w-[calc(100vw-20px)] max-shell-sm:-mt-2 max-w-[var(--radix-dropdown-menu-content-available-width)] motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out)_both]"
