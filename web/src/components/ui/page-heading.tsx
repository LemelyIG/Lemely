import type { ComponentProps } from "react"
import { cn } from "@/lib/utils"

/*
 * Every student and teacher screen's top heading (native frame D11). On the native
 * frame the shell's large title already shows the page title, so a heading that
 * repeats it is visually hidden there (`native:sr-only`) and stays the page's one
 * h1 for assistive technology; the large title itself is aria-hidden. Desktop,
 * tablet and `other` see the heading as before. `repeatsTitle` is required: say
 * whether this heading names the same page as the shell title.
 */
export function PageHeading({ repeatsTitle, className, ...props }: ComponentProps<"h1"> & { repeatsTitle: boolean }) {
  return <h1 data-page-heading={repeatsTitle ? "title" : "own"} className={cn(className, repeatsTitle && "native:sr-only")} {...props} />
}
