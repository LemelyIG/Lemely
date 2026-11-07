const RING_COLOR: Record<string, string> = {
  "A*": "var(--color-grade-a-star)",
  A: "var(--color-grade-a)",
  B: "var(--color-grade-b)",
  // Design A moves C off reward gold to a darker bronze-olive (`--sh-grade-c`).
  C: "var(--color-grade-c-shell)",
  D: "var(--color-grade-d)",
  E: "var(--color-grade-e)",
}

/** Design A `.as-ring`: the subject's grade in a 28px ring filled to `pct`. */
export function GradeRing({ grade, pct }: { grade: string; pct: number }) {
  const color = RING_COLOR[grade] ?? "var(--color-on-surface-variant)"
  const p = Math.max(0, Math.min(100, Math.round(pct)))
  return (
    <span
      aria-hidden="true"
      className="relative grid size-7 flex-none place-items-center rounded-pill text-2xs leading-none font-extrabold text-on-surface before:absolute before:inset-[3px] before:rounded-pill before:bg-surface-container-lowest dark:before:bg-surface-container-high"
      style={{ background: `conic-gradient(${color} ${p}%, var(--color-surface-container-high) 0)` }}
    >
      <b className="relative">{grade}</b>
    </span>
  )
}
