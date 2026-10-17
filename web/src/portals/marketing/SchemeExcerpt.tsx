/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B. */
import { useRef } from "react"
import { Chip } from "@/components/ui/chip"
import { schemeExcerpt } from "./data"
import { useScrollDraw } from "./motion"

/*
 * `SchemeExcerpt` — design-import-spec.md, "Components to build". A drawn
 * accent rule at inline-start (`.scheme::before`, `marketing.css`), a
 * metadata head naming the exact scheme excerpt, three `dt`/`dd` scheme
 * lines, and a closing `Marginalia`.
 *
 * No `Card` wrapper here — the spec gives this visual (unlike the trust
 * band's and the two `split--flip` sections') no `.drift` parallax class
 * either, matching `Landing.tsx`'s own note on that split. `.scheme` is the
 * whole of this component's chrome.
 */
export function SchemeExcerpt() {
  const ref = useRef<HTMLDivElement>(null)
  useScrollDraw(ref)

  return (
    <div className="scheme" ref={ref}>
      <div className="scheme__head text-data-sm">
        {schemeExcerpt.meta}
        <Chip tone="neutral">Example</Chip>
      </div>
      <dl className="scheme__lines">
        {schemeExcerpt.lines.map((line) => (
          <div key={line.code}>
            <dt className="text-data-md">{line.code}</dt>
            <dd className="text-body-md">{line.text}</dd>
          </div>
        ))}
      </dl>
      <p className="scheme__hand text-hand" aria-hidden="true">
        {schemeExcerpt.hand}
      </p>
    </div>
  )
}
