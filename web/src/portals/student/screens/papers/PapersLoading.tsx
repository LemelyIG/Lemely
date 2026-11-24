/* Hallmark · pre-emit critique: P3 H3 E3 S4 R4 V3 */
import { SkeletonBlock } from "@/components/ui/skeleton"
import "../subject/subject.css"
import "./papers.css"

/** The page heading and six rows, in the sizes the loaded screen uses, so nothing jumps when the papers arrive. */
export function PapersLoading({ name }: { name: string }) {
  return (
    <div className="ap-skel" role="status" aria-label={`Loading ${name} papers`}>
      <SkeletonBlock announce={false} style={{ height: 52 }} />
      {Array.from({ length: 6 }, (_, i) => (
        <SkeletonBlock key={i} announce={false} style={{ height: 64 }} />
      ))}
    </div>
  )
}
