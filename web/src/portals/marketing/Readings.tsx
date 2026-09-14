/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B.
   Every panel's title, body and points are verbatim from the design-import
   controller (the earlier gap — synthesized body/points copy while waiting
   on the spec's full Readings quotes — is closed; see data.ts's comment on
   `readings`). */
import { useState } from "react"
import { Check } from "@phosphor-icons/react"
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs"
import { readings } from "./data"

/*
 * `Readings` — design-import-spec.md, "Readings — the three-way switcher".
 * `Tabs` labelled "Who is reading" over teacher / student / parent, teacher
 * default. `ui/tabs` already builds the accessible tablist (roving
 * tabindex, arrow keys, `aria-selected`) and unmounts inactive panels, so
 * this component only supplies the tab definitions and each panel's
 * content.
 *
 * Each panel additionally wraps its content in `role="region"
 * aria-live="polite"` (spec: "Panel is `role="region"` `aria-live="polite"`")
 * — nested inside `TabsPanel`'s own `role="tabpanel"`, which is valid ARIA
 * (a tabpanel may contain a landmark) and gives assistive tech a live region
 * that announces the new reading's content on every switch, since switching
 * tabs here changes the whole panel rather than revealing/hiding a static
 * one.
 */
export function Readings() {
  const [active, setActive] = useState<(typeof readings)[number]["id"]>("teacher")

  return (
    <Tabs value={active} onValueChange={(v) => setActive(v as typeof active)}>
      <TabsList
        label="Who is reading"
        tabs={readings.map((panel) => ({ value: panel.id, label: panel.label }))}
      />
      {readings.map((panel) => (
        <TabsPanel value={panel.id} key={panel.id}>
          <div
            role="region"
            aria-live="polite"
            aria-label={panel.label}
            className="readings__panel"
          >
            <h3 className="text-display-md text-ink text-balance">{panel.title}</h3>
            <p className="readings__body text-body-lg text-pretty">{panel.body}</p>
            <ul className="readings__points">
              {panel.points.map((point) => (
                <li key={point}>
                  <Check size={16} weight="bold" className="text-ok" aria-hidden />
                  <span className="text-body-md">{point}</span>
                </li>
              ))}
            </ul>
          </div>
        </TabsPanel>
      ))}
    </Tabs>
  )
}
