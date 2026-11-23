/* Hallmark · pre-emit critique: P4 H3 E4 S4 R4 V3 */
import { SkeletonBlock } from "@/components/ui/skeleton"
import "./subject.css"

const BARS = [38, 50, 56, 84, 100]

/**
 * Mock L_P: title bar, five bars, the tip block, three rows. Right column rows from 768px.
 * One labelled status region announces the load once; the blocks inside stay silent.
 */
export function SubjectLoading({ name }: { name: string }) {
  return (
    <div className="sj-layout" role="status" aria-busy="true" aria-label={`Loading ${name}`}>
      <div className="sj-col sj-skel">
        <SkeletonBlock announce={false} style={{ width: 150, height: 22 }} />
        <div className="sj-skelbars">
          {BARS.map((h) => (
            <SkeletonBlock key={h} announce={false} style={{ height: `${h}%` }} />
          ))}
        </div>
        <SkeletonBlock announce={false} style={{ height: 50, borderRadius: 16 }} />
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} announce={false} style={{ height: 52 }} />
        ))}
      </div>
      <div className="sj-col sj-skel sj-col--aside-first-run">
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} announce={false} style={{ height: 52 }} />
        ))}
      </div>
    </div>
  )
}
