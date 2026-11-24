import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { HomeStage } from "@/portals/student/home/HomeStage"
import type { StageVm } from "@/portals/student/home/model"

/** The real HomeStage, server-rendered. */
export function stageHtml(vm: StageVm): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(HomeStage, { stage: vm, onNotNow: () => {} })),
  )
}

const ENTITIES: Record<string, string> = { "&#x27;": "'", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"' }

/**
 * Everything Binny's bubble says, as the reader gets it: the text inside the one `aria-live` paragraph, tags
 * stripped (so a Mono span counts as plain words) and entities decoded. Greeting, line, anything else rendered
 * in that paragraph, on every viewport: CSS-hidden text is still in this string, which is the point.
 */
export function bubbleText(vm: StageVm): string {
  const match = /<p\b[^>]*aria-live="polite"[^>]*>([\s\S]*?)<\/p>/.exec(stageHtml(vm))
  if (!match) throw new Error("HomeStage rendered no aria-live bubble")
  return match[1]!
    .replace(/<[^>]*>/g, "")
    .replace(/&#x27;|&amp;|&lt;|&gt;|&quot;/g, (e) => ENTITIES[e]!)
    .replace(/\s+/g, " ")
    .trim()
}

export function wordsIn(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length
}
