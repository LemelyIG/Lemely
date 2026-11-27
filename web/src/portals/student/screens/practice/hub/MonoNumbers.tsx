/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Fragment } from "react"

/**
 * Sets every run of digits in a line of copy in Mono (the Numbers Are Measured
 * Rule). The text is split, never changed, so the line still reads whole to
 * assistive tech and copy-paste.
 */
export function MonoNumbers({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\d+)/).map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="font-mono">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}
