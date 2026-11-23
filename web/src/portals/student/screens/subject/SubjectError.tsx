/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { Binny } from "@/components/redesign"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { links } from "./subjectModel"
import "./subject.css"

/** Mock E_P. Any failed first load except the two absence 404s, which go to first run. Binny says nothing: the heading does. */
export function SubjectError({ name, onRetry }: { name: string; onRetry: () => void }) {
  return (
    <div className="sj-err" role="alert">
      <Binny mood="sad" size={96} motion="idle" aria-hidden={true} />
      <h2>We couldn’t load {name}</h2>
      <p>Check your connection, then try again. Your papers are safe.</p>
      <button type="button" className={cn(buttonVariants({ variant: "primary", size: "lg" }), "sj-go")} onClick={onRetry}>
        Try again
      </button>
      <Link to={links.home} className="sj-upl">
        Back to Home
      </Link>
    </div>
  )
}
