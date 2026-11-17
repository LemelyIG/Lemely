/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { HairRow, HairRows } from "@/components/redesign"
import { homeRoutes } from "./routes"
import type { HomeVm } from "./model"
import { SectionLink } from "./SectionLink"

export function WinBack({ rows }: { rows: HomeVm["win"] }) {
  return (
    <section aria-labelledby="home-win" className="mt-1 grid">
      <SectionLink id="home-win" title="Win marks back" to={rows[0]?.to ?? homeRoutes.scan} />
      {rows.length > 0 ? (
        <HairRows aria-label="Topics to win marks back">
          {rows.map((r) => (
            <HairRow
              key={r.to}
              to={r.to}
              title={r.topic}
              sub={r.sub}
              trailing={
                <span className="font-mono text-[17px] font-bold leading-none tracking-[-0.02em] text-primary">
                  +{r.marks}
                  <small className="font-sans text-[12px] font-semibold tracking-normal text-on-surface-variant">{r.marks === 1 ? " mark" : " marks"}</small>
                </span>
              }
            />
          ))}
        </HairRows>
      ) : (
        <p className="py-3 text-[13px] text-on-surface-variant">Lost marks from your next paper show up here.</p>
      )}
    </section>
  )
}
